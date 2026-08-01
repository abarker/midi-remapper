"""
bankset.py

BankSet class: a named collection of MIDI event mapping banks.

This module has no mididings dependency.  All mididings interaction is
handled via the output_fn parameter (injected by dispatcher.py) and the
build_event / event_key / is_release functions imported from midi.py.

See the config.py module docstring for the full schema of bank entry
types and sequence item formats.
"""
import threading
import time

from midi_event_remapper.midi import build_event, event_key, is_release

# Delays at or below this threshold are sent synchronously rather than
# spawning a threading.Timer.  Any delay <= 1 ms is musically meaningless
# (JACK buffer periods are longer), so the events are sent immediately.
# This lets configs use "delay": 0.001 as a no-op sentinel without spawning
# a thread, while still allowing real delays like 0.200 to use the timer.
# The smallest meaningful real delay is therefore 0.002 s (2 ms).
_IMMEDIATE_DELAY_S = 0.001


def _wall_clock():
    """Return the current local wall-clock time as 'HH:MM:SS.mmm'.

    Used only by the stuck-thread and overrun warnings below, so that a
    stall can be lined up against 'dmesg -T' / 'journalctl -k' and against
    the timestamped '[in]' lines from dispatcher.py.  Those warnings fire
    rarely, so the formatting cost does not matter here -- do not call
    this from the event hot path, which under --jack-rt runs inside the
    JACK process callback.
    """
    t = time.time()
    return "%s.%03d" % (time.strftime("%H:%M:%S", time.localtime(t)),
                        int((t % 1) * 1000))


def _entry_sequences(value):
    """Yield every sequence list from a raw bank entry value.

    Handles all entry shapes: direct (list), gesture (dict with
    'single'/'double'/... values that are lists), and toggle (dict
    with 'a'/'b' values that are lists).
    """
    if isinstance(value, list):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            if isinstance(v, list):
                yield v


def _validate_osc_args(args):
    """Validate the 'args' list of an OSC send item.

    Returns an error string on failure, or None if valid.
    Each element must be int, float, or str (booleans excluded).
    """
    if not isinstance(args, list):
        return "must be a list"
    for a in args:
        if isinstance(a, bool) or not isinstance(a, (int, float, str)):
            return (
                f"elements must be int, float, or str "
                f"(got {type(a).__name__!r})"
            )
    return None


def _parse_transport_cmd(s):
    """Parse a JACK_TRANSPORT 'transport' string.

    Returns a tuple on success:
        ('start',)
        ('stop',)
        ('locate', frame_int)
    Returns None if the string is not a recognised command.
    """
    s = s.strip()
    if s == "start":
        return ("start",)
    if s == "stop":
        return ("stop",)
    if s.startswith("locate"):
        parts = s.split()
        if len(parts) == 2:
            try:
                frame = int(parts[1])
                if frame >= 0:
                    return ("locate", frame)
            except ValueError:
                pass
    return None

class BankSet:
    """
    A named collection of banks.  One bank is active at a time.

    Each bank is a dict mapping event keys (strings or tuples of strings)
    to behaviour definitions.  The behaviour type is inferred from the
    shape of the value:

        List value               -> direct: fires immediately, no state
        Dict with a / b          -> toggle: alternates between two sequences
        Dict with any of         -> gesture: unified handler for single,
          single/double/triple/     double, triple press and long hold.
          long                      'long' requires a momentary input
                                    (CC or NOTE) that sends a release signal.
                                    'single' behaves as a tap when 'long'
                                    is also defined.
        Tuple key                -> chord: all keys must arrive within
                                    chord_window_ms; falls back to
                                    individual dispatch if incomplete.

    Parameters
    ----------
    name : str
        Human-readable identifier, used in debug output.
    banks : dict
        Maps bank name strings to bank dicts.
    active_bank : str
        Name of the initially active bank.
    output_fn : callable or None
        Called with a single mididings event to emit output from timer
        callbacks.  Set to engine.output_event by dispatcher.py.
    debug : bool
        Whether to print diagnostic output.
    data_offset : int
        Passed through to validate(); should match the mididings
        DATA_OFFSET setting (1 or 0).
    debounce_ms : int
        Default toggle debounce window in milliseconds.
    multi_press_window_ms : int
        Window for double/triple press accumulation in milliseconds.
    chord_window_ms : int
        Window within which chord keys must all arrive in milliseconds.
    long_press_ms : int
        Default long-press threshold in milliseconds.
    """

    # Config dict keys that are metadata, not action labels.
    _META_KEYS    = frozenset({"long_ms", "trigger_value", "debounce_ms",
                               "repeat_delay_ms", "repeat_ms", "multi_ms",
                               "repeat_accel", "eager_single"})
    # Bank-level keys that are not MIDI event mappings and are skipped during
    # lookup table construction and validation.  "_display" is normally
    # stripped by the loader before the BankSet is constructed; this acts as
    # a safety net for BankSets built by other means.
    _BANK_META_KEYS = frozenset({"_display"})
    # Valid action labels for gesture entries.
    _GESTURE_KEYS = frozenset({"single", "double", "triple", "long", "repeat"})

    def __init__(
        self,
        name,
        banks,
        active_bank           = "default",
        output_fn             = None,
        display_fn            = None,
        display_styles        = None,
        debug                 = False,
        data_offset           = 1,
        debounce_ms           = 60,
        multi_press_window_ms = 300,
        chord_window_ms       = 80,
        long_press_ms         = 500,
    ):
        self.name        = name
        self.banks       = banks
        self.active_bank = active_bank

        self._output_fn             = output_fn
        self._display_fn            = display_fn  # called on bank switch: fn(bankset_name, bank_name, style)
        self._display_styles        = display_styles or {}  # bank_name -> style dict
        self._debug                 = debug
        self._data_offset           = data_offset
        self._debounce_ms           = debounce_ms
        self._multi_press_window_ms = multi_press_window_ms
        self._chord_window_ms       = chord_window_ms
        self._long_press_ms         = long_press_ms
        self._repeat_delay_ms       = 500   # default: ms before first repeat
        self._repeat_ms             = 100   # default: ms between repeats

        # Set to False by cancel_timers() so in-flight timer callbacks abort
        # instead of rescheduling or calling _output_fn on a dead BankSet.
        self._active = True

        # Toggle state. Persists across bank switches intentionally.
        self._toggle_states = {}   # key -> bool (False=a, True=b)
        self._toggle_ts     = {}   # key -> float (last trigger time)

        # Unified gesture state (replaces separate longpress / multipress dicts)
        self._gesture_counts     = {}  # key -> int   (accumulated press count)
        self._gesture_press_time = {}  # key -> float (time of most recent press)
        self._gesture_timers     = {}  # key -> Timer (multipress window timer)
        self._gesture_events     = {}  # key -> event (most recent press event)
        self._gesture_long_timers   = {} # key -> Timer (long-press threshold timer)
        self._gesture_long_fired    = set()  # keys where long already fired via timer
        self._gesture_repeat_timers = {} # key -> Timer (current pending repeat timer)
        self._gesture_repeat_fired  = set()  # keys where repeat has fired at least once

        # Chord state
        # frozenset -> {"arrived": set, "timer": Timer,
        #               "events":  {key: event},
        #               "press_times": {key: float}}
        self._chord_pending  = {}

        # Chord multi-press state
        # frozenset -> {"count": int, "timer": Timer, "event": event}
        self._chord_counts   = {}

        # Keys whose presses were consumed by a completed chord.
        # Their releases are suppressed to prevent them firing mappings
        # in whatever bank is active at release time.
        self._chord_consumed = set()

        # Keep timer references alive until they fire.
        self._timer_list = []

        # Per-thread tracking for delayed MIDI sends: (thread, due_at, desc).
        # Used by _cleanup_timers to detect threads stuck in _output_fn.
        self._delay_send_threads = []
        # Thread ids already warned about; cleared when the thread completes.
        self._stuck_delay_ids    = set()

        # Per-thread tracking for JACK_TRANSPORT calls: (thread, started_at,
        # desc).  Mirrors _delay_send_threads above, but tracks a running
        # call rather than a scheduled-but-not-yet-fired one: the entry is
        # recorded the instant the daemon thread starts, and _cleanup_timers
        # checks whether it's still alive well past a reasonable duration
        # for a local jack.Client call.  A stuck entry here means the thread
        # is parked inside jack_ctrl.transport_*(), most likely because the
        # JACK graph itself has stalled (e.g. another client wedged in its
        # process callback).  This does not detect a hang while it starts --
        # only a periodic check (driven by handle()) notices it after the
        # fact -- but it requires no new thread, lock, or change to how
        # transport calls are dispatched.
        self._transport_threads  = []
        self._stuck_transport_ids = set()

        # Timestamp of last leak check; drives the time-based cleanup trigger.
        self._last_leak_check    = 0.0

        # Precomputed lookup tables
        self._entry_types   = {}   # (bank_name, key) -> type string
        self._chord_members = {}   # bank_name -> {key -> [frozenset, ...]}

        self._build_lookup_tables()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_output_fn(self, fn):
        """Set the function used to emit events from timer callbacks."""
        self._output_fn = fn

    def cancel_timers(self):
        """Cancel all pending timers.  Called before discarding a BankSet on reload.

        Covers gesture (multipress window, long-press, repeat), chord window,
        chord multipress, and any delayed-send timers in _timer_list.

        ``_active`` is cleared first so that any callback already executing
        when this is called will abort rather than reschedule or call
        ``_output_fn`` on a dead BankSet.
        """
        self._active = False   # Must be first -- stops any in-flight reschedule.
        for t in self._gesture_timers.values():
            t.cancel()
        for t in self._gesture_long_timers.values():
            t.cancel()
        for t in self._gesture_repeat_timers.values():
            t.cancel()
        for pending in self._chord_pending.values():
            pending["timer"].cancel()
        for state in self._chord_counts.values():
            state["timer"].cancel()
        for t in self._timer_list:
            t.cancel()
        self._timer_list.clear()
        self._delay_send_threads.clear()
        self._stuck_delay_ids.clear()
        # Note: these are plain threading.Thread, not Timer -- there is no
        # .cancel() for a call already in flight.  Clearing the tracking
        # lists only stops *watching* a stuck thread; if one is genuinely
        # parked inside jack_ctrl.transport_*(), it remains running (as a
        # daemon thread) until the call returns or the process exits.
        self._transport_threads.clear()
        self._stuck_transport_ids.clear()

    @property
    def current_bank(self):
        return self.banks[self.active_bank]

    def switch_bank(self, name):
        if name not in self.banks:
            raise ValueError(
                f"BankSet {self.name!r}: unknown bank {name!r}. "
                f"Available: {list(self.banks.keys())}"
            )
        if self._debug:
            print(
                f"\n{'='*50}\n"
                f"  BankSet [{self.name}]  bank: "
                f"{self.active_bank!r} -> {name!r}\n"
                f"{'='*50}\n"
            )
        self.active_bank = name
        if self._display_fn is not None:
            try:
                style = self._display_styles.get(name)
                self._display_fn(self.name, name, style)
            except Exception:
                pass  # never let display errors crash the MIDI handler

    def handle(self, event):
        """
        Process one incoming mididings event.

        Returns a list of mididings events to emit immediately, or None
        if this BankSet does not handle the event (allowing the dispatcher
        to try the next BankSet or pass the event through unchanged).

        Delayed and timer-fired events are dispatched internally via
        self._output_fn.
        """
        key = event_key(event)
        if key is None:
            return None

        bank_name     = self.active_bank
        bank          = self.banks[bank_name]
        chord_members = self._chord_members.get(bank_name, {})

        if self._debug:
            print(f"[BankSet:{self.name}] handle key={key}")

        # Periodically remove dead timers to prevent unbounded growth, and
        # check for delay-send or transport threads that may be stuck.
        if len(self._timer_list) > 50:
            self._cleanup_timers()
        elif self._delay_send_threads or self._transport_threads:
            _now = time.monotonic()
            if _now - self._last_leak_check > 5.0:
                self._last_leak_check = _now
                self._cleanup_timers()

        rel = is_release(event)

        # ── Release handling ───────────────────────────────────────────
        if rel:
            # Suppress releases for keys consumed by a completed chord.
            if key in self._chord_consumed:
                self._chord_consumed.discard(key)
                return []

            # Long press already fired via timer: suppress the release.
            if key in self._gesture_long_fired:
                self._gesture_long_fired.discard(key)
                return []

            # Gesture release: long-press detection.
            # Only intercept if we recorded a press for this key.
            if key in self._gesture_press_time:
                etype = self._entry_types.get((bank_name, key))
                if etype == "gesture":
                    return self._handle_gesture_release(
                        key, bank.get(key, {}), event
                    )

            # Fast chord dismissal on CC=0 release.
            fallback = self._maybe_dismiss_fast_chord(key, bank_name, bank, event)
            if fallback is not None:
                return fallback

            # Determine how to handle the release based on entry type.
            etype = self._entry_types.get((bank_name, key))
            if etype is None:
                return None        # unmapped: pass release through unchanged
            if etype == "direct":
                pass               # fall through to normal dispatch
            elif etype == "gesture":
                # No prior press recorded.  If 'long' is defined, pass
                # through so the orphan release reaches downstream devices.
                # If no 'long', suppress: nothing timing-based is pending.
                entry = bank.get(key, {})
                return None if "long" in entry else []
            else:
                return []          # toggle/chord: suppress release

        # ── Chord participation ────────────────────────────────────────
        # CC=0/NoteOff releases are excluded above and never reach here.
        if not rel and key in chord_members:
            result = self._handle_chord_arrival(
                key, chord_members[key], bank, event
            )
            # None: window opened/updated, not yet complete -- suppress.
            # list: chord just completed, return events to mididings.
            return result if result is not None else []

        # ── Normal single-key dispatch ─────────────────────────────────
        if key not in bank:
            return None

        etype = self._entry_types[(bank_name, key)]
        entry = bank[key]

        if etype == "direct":
            return self._execute_sequence(entry, event)
        elif etype == "toggle":
            return self._handle_toggle(key, entry, event)
        elif etype == "gesture":
            return self._handle_gesture_press(key, entry, event)

        return None

    def validate(self):
        """
        Check all bank entries for configuration errors.
        Returns (errors, warnings) — both lists of strings.
        errors:   non-empty means the config is invalid and should not run.
        warnings: non-empty means something works but is likely misconfigured.
        Called at startup before run() and on every hot reload.
        """
        errors   = []
        warnings = []
        pc_min = self._data_offset
        pc_max = 127 + self._data_offset
        ch_min = self._data_offset
        ch_max = 15  + self._data_offset

        def check_sequence(seq, ctx):
            for i, item in enumerate(seq):
                if "send" not in item:
                    errors.append(f"{ctx}[{i}]: missing required 'send' key")
                    continue
                send = item["send"]
                if send == "BANK":
                    if "bank" not in item:
                        errors.append(
                            f"{ctx}[{i}]: BANK send missing 'bank' key"
                        )
                    elif item["bank"] not in self.banks:
                        errors.append(
                            f"{ctx}[{i}]: BANK send references unknown "
                            f"bank {item['bank']!r}"
                        )
                    continue
                if send == "CMD":
                    if "cmd" not in item:
                        errors.append(
                            f"{ctx}[{i}]: CMD send missing required 'cmd' key"
                        )
                    elif not isinstance(item["cmd"], str) or \
                         not item["cmd"].strip():
                        errors.append(
                            f"{ctx}[{i}]: CMD 'cmd' must be a non-empty string"
                        )
                    continue
                if send == "JACK_TRANSPORT":
                    transport = item.get("transport", "")
                    if not isinstance(transport, str) or not transport.strip():
                        errors.append(
                            f"{ctx}[{i}]: JACK_TRANSPORT missing required "
                            f"'transport' key"
                        )
                    elif _parse_transport_cmd(transport) is None:
                        errors.append(
                            f"{ctx}[{i}]: JACK_TRANSPORT 'transport' must be "
                            f"'start', 'stop', or 'locate <frame>' "
                            f"(got {transport!r})"
                        )
                    continue
                if send == "OSC":
                    host    = item.get("host", "")
                    port    = item.get("port")
                    address = item.get("address", "")
                    if not isinstance(host, str) or not host.strip():
                        errors.append(
                            f"{ctx}[{i}]: OSC missing required 'host'"
                        )
                    if port is None:
                        errors.append(
                            f"{ctx}[{i}]: OSC missing required 'port'"
                        )
                    elif isinstance(port, bool) or not isinstance(port, int) \
                            or not (1 <= port <= 65535):
                        errors.append(
                            f"{ctx}[{i}]: OSC 'port' must be an integer "
                            f"1-65535 (got {port!r})"
                        )
                    if not isinstance(address, str) or \
                            not address.startswith("/"):
                        errors.append(
                            f"{ctx}[{i}]: OSC 'address' must be a string "
                            f"starting with '/' (got {address!r})"
                        )
                    if "args" in item:
                        err = _validate_osc_args(item["args"])
                        if err:
                            errors.append(
                                f"{ctx}[{i}]: OSC 'args' {err}"
                            )
                    continue
                # Wrong keyword checks
                if send.startswith("CC") and "velocity" in item:
                    errors.append(
                        f"{ctx}[{i}]: CC send uses 'velocity' -- "
                        f"did you mean 'value'?"
                    )
                if send.startswith("NOTE") and "value" in item:
                    errors.append(
                        f"{ctx}[{i}]: NOTE send uses 'value' -- "
                        f"did you mean 'velocity'?"
                    )
                # Per-item channel override (CC/PC/NOTE only; SYSEX has no channel)
                if "channel" in item and send not in ("SYSEX",):
                    ch = item["channel"]
                    if isinstance(ch, bool) or not isinstance(ch, int):
                        errors.append(
                            f"{ctx}[{i}]: 'channel' must be an integer "
                            f"{ch_min}-{ch_max} (got {ch!r})"
                        )
                    elif not (ch_min <= ch <= ch_max):
                        errors.append(
                            f"{ctx}[{i}]: 'channel' {ch} out of range "
                            f"(valid {ch_min}-{ch_max} with "
                            f"data_offset={self._data_offset})"
                        )
                # Range checks
                if send.startswith("PC"):
                    try:
                        n = int(send[2:])
                        if not (pc_min <= n <= pc_max):
                            errors.append(
                                f"{ctx}[{i}]: {send!r} out of range "
                                f"(valid {pc_min}-{pc_max} with "
                                f"data_offset={self._data_offset})"
                            )
                    except ValueError:
                        errors.append(f"{ctx}[{i}]: malformed send {send!r}")
                elif send.startswith("CC"):
                    try:
                        n = int(send[2:])
                        if not (0 <= n <= 127):
                            errors.append(
                                f"{ctx}[{i}]: {send!r} CC number "
                                f"out of range (0-127)"
                            )
                    except ValueError:
                        errors.append(f"{ctx}[{i}]: malformed send {send!r}")
                elif send.startswith("NOTE"):
                    try:
                        n = int(send[4:])
                        if not (0 <= n <= 127):
                            errors.append(
                                f"{ctx}[{i}]: {send!r} note number "
                                f"out of range (0-127)"
                            )
                    except ValueError:
                        errors.append(f"{ctx}[{i}]: malformed send {send!r}")
                elif send not in ("SYSEX", "CMD", "JACK_TRANSPORT", "OSC"):
                    errors.append(
                        f"{ctx}[{i}]: unrecognised send {send!r}"
                    )

        def check_trigger_value(tv, ctx):
            """Validate trigger_value syntax."""
            def check_one(spec):
                if isinstance(spec, int):
                    return
                if isinstance(spec, str):
                    s = spec.strip()
                    try:
                        for prefix in (">=", "<=", ">", "<"):
                            if s.startswith(prefix):
                                int(s[len(prefix):].strip())
                                return
                        if '-' in s:
                            lo, hi = s.split('-', 1)
                            int(lo.strip())
                            int(hi.strip())
                            return
                        int(s)
                    except ValueError:
                        errors.append(
                            f"{ctx}: invalid trigger_value spec {spec!r}"
                        )
                    return
                errors.append(
                    f"{ctx}: trigger_value item must be int or str, "
                    f"got {type(spec).__name__}"
                )
            if isinstance(tv, list):
                for item in tv:
                    check_one(item)
            else:
                check_one(tv)

        def check_entry(key, value, bank_name):
            ctx = f"BankSet[{self.name!r}][{bank_name!r}][{key!r}]"
            try:
                etype = self._classify(key, value)
            except ValueError as exc:
                errors.append(str(exc))
                return
            if etype == "direct":
                check_sequence(value, ctx)
            elif etype == "toggle":
                for state in ("a", "b"):
                    if state not in value:
                        errors.append(
                            f"{ctx}: missing required state {state!r}"
                        )
                    else:
                        check_sequence(value[state], f"{ctx}[{state!r}]")
            elif etype == "gesture":
                # 'long' and 'repeat' both require a momentary input
                for hold_label in ("long", "repeat"):
                    if hold_label in value and isinstance(key, str) and \
                       key.startswith("PC"):
                        errors.append(
                            f"{ctx}: {hold_label!r} requires a momentary "
                            f"input (CC or NOTE); PC events have no release "
                            f"signal"
                        )
                # 'long' and 'repeat' are mutually exclusive
                if "long" in value and "repeat" in value:
                    errors.append(
                        f"{ctx}: 'long' and 'repeat' cannot both be defined "
                        f"in the same entry -- 'long' fires once at threshold, "
                        f"'repeat' fires repeatedly; choose one"
                    )
                if "trigger_value" in value:
                    check_trigger_value(value["trigger_value"], ctx)
                for label in ("single", "double", "triple", "long", "repeat"):
                    if label in value:
                        check_sequence(value[label], f"{ctx}[{label!r}]")
                # repeat_accel tiers: each may override the repeat
                # sequence, the repeat interval, or both.
                accel = value.get("repeat_accel")
                if accel is not None:
                    if "repeat" not in value:
                        errors.append(
                            f"{ctx}: 'repeat_accel' requires 'repeat' "
                            f"at the top level"
                        )
                    if not isinstance(accel, list):
                        errors.append(
                            f"{ctx}: 'repeat_accel' must be a list"
                        )
                    else:
                        for j, tier in enumerate(accel):
                            tctx = f"{ctx} repeat_accel[{j}]"
                            if not isinstance(tier, dict):
                                errors.append(
                                    f"{tctx}: must be a dict"
                                )
                                continue
                            if "after_ms" not in tier:
                                errors.append(
                                    f"{tctx}: missing required 'after_ms'"
                                )
                            else:
                                after = tier["after_ms"]
                                if not isinstance(after, (int, float)) \
                                        or after <= 0:
                                    errors.append(
                                        f"{tctx}: 'after_ms' must be a "
                                        f"positive number"
                                    )
                            has_repeat_key = "repeat"    in tier
                            has_repeat_ms  = "repeat_ms" in tier
                            if not has_repeat_key and not has_repeat_ms:
                                errors.append(
                                    f"{tctx}: must specify at least one "
                                    f"of 'repeat' or 'repeat_ms'"
                                )
                            if has_repeat_key:
                                check_sequence(
                                    tier["repeat"],
                                    f"{tctx}['repeat']"
                                )
                            if has_repeat_ms:
                                ms = tier["repeat_ms"]
                                if not isinstance(ms, (int, float)) \
                                        or ms <= 0:
                                    errors.append(
                                        f"{tctx}: 'repeat_ms' must be "
                                        f"a positive number"
                                    )
                # eager_single validation (§5)
                if "eager_single" in value:
                    es = value["eager_single"]
                    # §5.3: must be a bool
                    if not isinstance(es, bool):
                        errors.append(
                            f"{ctx}: 'eager_single' must be True or False "
                            f"(got {es!r})"
                        )
                    elif es:
                        # §5.2: must have a 'single' action to fire eagerly
                        if "single" not in value:
                            errors.append(
                                f"{ctx}: 'eager_single' is set but no "
                                f"'single' action is defined -- "
                                f"nothing to fire eagerly"
                            )
                        else:
                            # §5.4: BANK send inside an eager single is
                            # forbidden -- a mid-gesture bank switch corrupts
                            # deferred-action routing and gesture state.
                            for _item in value["single"]:
                                if (isinstance(_item, dict)
                                        and _item.get("send") == "BANK"):
                                    errors.append(
                                        f"{ctx}: 'BANK' send is not allowed "
                                        f"in the 'single' sequence of an "
                                        f"eager_single entry -- switching "
                                        f"banks mid-gesture would leave the "
                                        f"deferred action bound to the "
                                        f"wrong bank"
                                    )
                                    break
                        # §5.1: flag has no effect when there are no
                        # deferred labels -- 'single' already fires
                        # immediately in that case.
                        has_deferred = any(k in value
                                           for k in ("double", "triple",
                                                     "long", "repeat"))
                        if not has_deferred:
                            warnings.append(
                                f"{ctx}: 'eager_single' is set but no "
                                f"'double', 'triple', 'long', or 'repeat' "
                                f"is defined -- 'single' already fires "
                                f"immediately; the flag has no effect"
                            )
            elif etype == "chord":
                if "long" in value:
                    errors.append(
                        f"{ctx}: 'long' is not valid in a chord entry -- "
                        f"chords have no individual release signal"
                    )
                for label in ("single", "double", "triple"):
                    if label in value:
                        check_sequence(value[label], f"{ctx}[{label!r}]")

        for bank_name, bank in self.banks.items():
            for key, value in bank.items():
                if key in self._BANK_META_KEYS:
                    continue
                check_entry(key, value, bank_name)

        if self.active_bank not in self.banks:
            errors.append(
                f"BankSet {self.name!r}: active_bank "
                f"{self.active_bank!r} not found in banks"
            )

        return errors, warnings

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _cleanup_timers(self):
        """Remove completed timers and warn about hung delay-send or
        JACK_TRANSPORT threads.

        Each chord window, gesture timer, and delayed send creates a
        threading.Timer (which is a thread).  Without cleanup, the list
        grows indefinitely with dead threads, eventually causing hangs.
        Called from handle() when the list exceeds 50 entries OR when
        delay-send / transport threads are pending and 5 seconds have
        elapsed since the last check.

        Hung detection (delay sends): a delay-send thread that is still
        alive more than 1 second past its scheduled fire time is probably
        blocked inside _output_fn waiting on a stalled JACK graph.

        Hung detection (JACK_TRANSPORT): a transport thread that has been
        running for more than 1 second is probably blocked inside
        jack_ctrl.transport_*() -- a local JACK client call ordinarily
        returns in well under that.  The likely cause is the JACK graph
        itself having stalled (e.g. another client stuck in its own
        process callback), not anything internal to this thread.

        Both warnings print once per thread, not on every subsequent check.
        Note: this only reports a hang *after* a check happens to run while
        the thread is still stuck -- it cannot detect one the instant it
        starts, and it stops watching a thread once cancel_timers() clears
        the tracking list (e.g. on a config reload).
        """
        now = time.monotonic()
        self._timer_list = [t for t in self._timer_list if t.is_alive()]

        live = []
        for t, due_at, desc in self._delay_send_threads:
            if t.is_alive():
                overdue = now - due_at
                if overdue > 1.0 and id(t) not in self._stuck_delay_ids:
                    self._stuck_delay_ids.add(id(t))
                    print(
                        f"[{self.name}] {_wall_clock()} WARNING: "
                        f"delayed MIDI send stuck "
                        f"{overdue:.1f}s past due — _output_fn may be "
                        f"blocked (JACK graph stalled?): {desc}"
                    )
                live.append((t, due_at, desc))
            else:
                # Thread completed normally; retire its warned-id if present.
                self._stuck_delay_ids.discard(id(t))
        self._delay_send_threads = live

        live_transport = []
        for t, started_at, desc in self._transport_threads:
            if t.is_alive():
                running_for = now - started_at
                if running_for > 1.0 and id(t) not in self._stuck_transport_ids:
                    self._stuck_transport_ids.add(id(t))
                    print(
                        f"[{self.name}] {_wall_clock()} WARNING: "
                        f"JACK transport call stuck "
                        f"{running_for:.1f}s — jack.Client call may be "
                        f"blocked (JACK graph stalled?): {desc}"
                    )
                live_transport.append((t, started_at, desc))
            else:
                self._stuck_transport_ids.discard(id(t))
        self._transport_threads = live_transport

    def _build_lookup_tables(self):
        for bank_name, bank in self.banks.items():
            self._chord_members[bank_name] = {}
            for key, value in bank.items():
                if key in self._BANK_META_KEYS:
                    continue
                try:
                    etype = self._classify(key, value)
                except ValueError:
                    # Unclassifiable: store sentinel so validate() reports it
                    # cleanly rather than crashing __init__.
                    etype = "unknown"
                self._entry_types[(bank_name, key)] = etype
                if isinstance(key, tuple):
                    fk = frozenset(key)
                    for k in key:
                        self._chord_members[bank_name].setdefault(
                            k, []
                        ).append(fk)

        # Pre-initialise external clients for JACK_TRANSPORT and OSC sends
        # found in this config.  Done here (loading time, main thread) so
        # connection overhead does not occur mid-session.  Each block is
        # wrapped in try/except so --validate and test runs (where neither
        # JACK nor an OSC server need be running) work normally.
        _jack_transport = False
        _osc_targets    = set()
        for _bn, _bank in self.banks.items():
            for _k, _v in _bank.items():
                if _k in self._BANK_META_KEYS:
                    continue
                for _seq in _entry_sequences(_v):
                    for _item in _seq:
                        if not isinstance(_item, dict):
                            continue
                        _s = _item.get("send")
                        if _s == "JACK_TRANSPORT":
                            _jack_transport = True
                        elif _s == "OSC":
                            _h = _item.get("host", "")
                            _p = _item.get("port", 0)
                            if (_h and isinstance(_p, int)
                                    and not isinstance(_p, bool)
                                    and 1 <= _p <= 65535):
                                _osc_targets.add((_h, _p))

        if _jack_transport:
            try:
                from midi_event_remapper import jack_ctrl
                jack_ctrl.preinit()
            except Exception:
                pass  # JACK not running; will retry on first use

        if _osc_targets:
            try:
                from midi_event_remapper import osc_ctrl
                for _h, _p in _osc_targets:
                    osc_ctrl.preinit(_h, _p)
            except Exception:
                pass  # pythonosc not installed or target unreachable

    def _classify(self, key, value):
        """Infer the behaviour type of a bank entry from its shape."""
        if isinstance(key, tuple):
            return "chord"
        if isinstance(value, list):
            return "direct"
        if isinstance(value, dict):
            action_keys = set(value.keys()) - self._META_KEYS
            if action_keys <= {"a", "b"}:
                return "toggle"
            if action_keys and action_keys <= self._GESTURE_KEYS:
                return "gesture"
        raise ValueError(
            f"BankSet {self.name!r}: cannot classify entry "
            f"key={key!r}, value={value!r}"
        )

    # ------------------------------------------------------------------
    # Sequence execution
    # ------------------------------------------------------------------

    def _execute_sequence(self, seq, event):
        """
        Execute a sequence list.  Immediate events are returned as a list.
        Delayed events are scheduled via threading.Timer.
        BANK sends are executed inline.
        Returns a list (possibly empty -- empty means "handled, emit nothing").
        """
        immediate = []
        for item in seq:
            send  = item.get("send", "")
            delay = float(item.get("delay", 0.0))

            if send == "BANK":
                self.switch_bank(item["bank"])
                continue

            if send == "CMD":
                cmd = item.get("cmd", "")
                if cmd:
                    if delay <= _IMMEDIATE_DELAY_S:
                        self._run_cmd(cmd)
                    else:
                        t = threading.Timer(delay, self._run_cmd, args=(cmd,))
                        t.daemon = True
                        t.start()
                        self._timer_list.append(t)
                continue

            if send == "JACK_TRANSPORT":
                transport = item.get("transport", "")
                if transport:
                    if delay <= _IMMEDIATE_DELAY_S:
                        self._run_jack_transport(transport)
                    else:
                        t = threading.Timer(
                            delay, self._run_jack_transport,
                            args=(transport,)
                        )
                        t.daemon = True
                        t.start()
                        self._timer_list.append(t)
                continue

            if send == "OSC":
                if delay <= _IMMEDIATE_DELAY_S:
                    self._run_osc_send(item)
                else:
                    t = threading.Timer(
                        delay, self._run_osc_send, args=(item,)
                    )
                    t.daemon = True
                    t.start()
                    self._timer_list.append(t)
                continue

            if item.get("press_only") and is_release(event):
                continue

            ev_out = build_event(
                item, event.port, event.channel,
                event_value=getattr(event, 'value', None)
            )

            if delay <= _IMMEDIATE_DELAY_S:
                immediate.append(ev_out)
                if self._debug:
                    print(f"  [seq] -> immediate: {ev_out}")
            else:
                if self._debug:
                    print(f"  [seq] -> in {delay:.3f}s: {ev_out}")
                _desc = str(ev_out)
                def _emit(ev=ev_out, desc=_desc):
                    if not self._active:
                        return
                    t0 = time.monotonic()
                    self._output_fn(ev)
                    elapsed = time.monotonic() - t0
                    if elapsed > 0.100:
                        print(
                            f"[{self.name}] {_wall_clock()} WARNING: "
                            f"_output_fn took "
                            f"{elapsed*1000:.0f}ms for delayed send: {desc}"
                        )
                _due = time.monotonic() + delay
                t = threading.Timer(delay, _emit)
                t.daemon = True
                t.start()
                self._timer_list.append(t)
                self._delay_send_threads.append((t, _due, _desc))

        return immediate

    def _run_cmd(self, cmd):
        """
        Run a shell command in a subprocess, non-blocking.

        The command is run via the shell so pipes, redirects, and shell
        builtins all work.  stdout and stderr are captured; in debug mode
        any output is printed after the process completes.

        Safe to call from both the mididings callback and timer threads.
        """
        import subprocess

        def run():
            try:
                result = subprocess.run(
                    cmd,
                    shell   = True,
                    capture_output = True,
                    text    = True,
                )
                if self._debug:
                    print(f"  [cmd] $ {cmd}")
                    if result.stdout.strip():
                        print(f"  [cmd] stdout: {result.stdout.strip()}")
                    if result.stderr.strip():
                        print(f"  [cmd] stderr: {result.stderr.strip()}")
                    if result.returncode != 0:
                        print(f"  [cmd] exit code: {result.returncode}")
            except Exception as e:
                if self._debug:
                    print(f"  [cmd] ERROR running {cmd!r}: {e}")

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def _run_jack_transport(self, transport_str):
        """
        Execute a JACK transport command via the persistent jack.Client.

        Runs in a daemon thread so it does not block the mididings
        callback.  Unlike CMD (which forks a subprocess), this calls the
        JACK C library directly via the existing client connection, writing
        to JACK shared memory.  No fork/exec occurs, so recording clients
        are not disturbed.

        Safe to call from both the mididings callback and timer threads.

        The thread is recorded in ``self._transport_threads`` so that
        ``_cleanup_timers`` can later notice if it never returns (see that
        method's docstring for what triggers a warning).
        """
        def run():
            try:
                from midi_event_remapper import jack_ctrl
                cmd = _parse_transport_cmd(transport_str)
                if cmd[0] == "start":
                    jack_ctrl.transport_start()
                elif cmd[0] == "stop":
                    jack_ctrl.transport_stop()
                else:  # locate -- frame is cmd[1], already validated
                    jack_ctrl.transport_locate(cmd[1])
                if self._debug:
                    print(f"  [jack_transport] {transport_str}")
            except Exception as e:
                if self._debug:
                    print(f"  [jack_transport] ERROR: {e}")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._transport_threads.append((t, time.monotonic(), transport_str))

    def _run_osc_send(self, item):
        """Send an OSC message via the persistent client pool.

        Runs in a daemon thread so it does not block the mididings
        callback.  Uses the pre-initialised ``osc_ctrl`` client for the
        target ``(host, port)`` pair; the UDP send itself is a single
        non-blocking syscall.
        """
        def run():
            try:
                from midi_event_remapper import osc_ctrl
                host    = item["host"]
                port    = item["port"]
                address = item["address"]
                args    = item.get("args", [])
                osc_ctrl.send(host, port, address, args)
                if self._debug:
                    print(
                        f"  [osc] {host}:{port} "
                        f"{address} {args}"
                    )
            except ModuleNotFoundError:
                # python-osc is not installed.  Always print this --
                # silent failure here would be very hard to diagnose.
                print(
                    "[osc] ERROR: python-osc is not installed.  "
                    "Install it with: pip install python-osc"
                )
            except Exception as e:
                if self._debug:
                    print(f"  [osc] ERROR: {e}")

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def _fire_sequence(self, seq, event):
        """
        Like _execute_sequence but routes immediate events through
        self._output_fn.  Used from timer callbacks where returning a
        value to mididings is not possible.

        Checks ``_active`` before emitting so that a callback which races
        past its own guard does not reach ``engine.output_event``.
        """
        if not self._active:
            return
        result = self._execute_sequence(seq, event)
        if result:
            for ev_out in result:
                self._output_fn(ev_out)

    # ------------------------------------------------------------------
    # Toggle
    # ------------------------------------------------------------------

    def _handle_toggle(self, key, entry, event):
        now      = time.time()
        debounce = entry.get("debounce_ms", self._debounce_ms) / 1000.0
        if now - self._toggle_ts.get(key, 0.0) < debounce:
            if self._debug:
                print(f"[toggle:{self.name}] debounced key={key}")
            return None
        self._toggle_ts[key] = now

        state     = not self._toggle_states.get(key, False)
        self._toggle_states[key] = state
        state_key = "a" if state else "b"
        if self._debug:
            print(
                f"[toggle:{self.name}] key={key} -> state {state_key.upper()}"
            )
        return self._execute_sequence(entry[state_key], event)

    # ------------------------------------------------------------------
    # Gesture (unified single / double / triple / long)
    # ------------------------------------------------------------------

    def _handle_gesture_press(self, key, entry, event):
        """
        Handle a press event for a gesture entry.

        If only 'single' is defined with no 'long' or multi-press labels,
        fires immediately with no timing delay.

        If 'long' is defined, starts a long_ms timer that fires the 'long'
        action immediately when the threshold is exceeded -- no need to wait
        for the release.  The release is suppressed when it eventually arrives.

        Otherwise accumulates press count and/or records press time,
        relying on _handle_gesture_release and _reset_gesture_timer to
        dispatch the final action.
        """
        if not self._matches_trigger_value(entry, event):
            return None   # trigger_value filter failed: pass through

        has_long   = "long"   in entry
        has_repeat = "repeat" in entry
        has_multi  = "double" in entry or "triple" in entry
        has_single = "single" in entry

        # Accumulate state
        self._gesture_counts[key] = self._gesture_counts.get(key, 0) + 1
        self._gesture_press_time[key] = time.time()
        self._gesture_events[key]     = event

        if not has_long and not has_repeat and not has_multi:
            # Only 'single' defined: fire immediately, no timing needed.
            self._gesture_counts.pop(key, None)
            self._gesture_press_time.pop(key, None)
            self._gesture_events.pop(key, None)
            if has_single:
                return self._execute_sequence(entry["single"], event)
            return []

        if has_multi and not has_long and not has_repeat:
            # Multi-press only: start the window timer on press.
            self._reset_gesture_timer(key, entry, event)

        if has_long:
            # Start a long-press timer that fires at threshold.
            self._start_long_timer(key, entry, event)

        if has_repeat:
            # Start the initial repeat delay timer.
            self._start_repeat_timer(key, entry, event, initial=True)

        # eager_single: fire 'single' immediately on the first press, then
        # let the deferred action (long/double/repeat) resolve normally.
        # The suppression guards in _reset_gesture_timer and
        # _handle_gesture_release prevent single from firing a second time.
        eager_events = []
        if (entry.get("eager_single")
                and has_single
                and self._gesture_counts[key] == 1):
            eager_events = self._execute_sequence(entry["single"], event)

        # Suppress the press; deferred dispatch happens on release or timer.
        return eager_events

    def _start_long_timer(self, key, entry, event):
        """
        Start (or restart) a timer that fires the 'long' action as soon as
        the hold threshold is exceeded.  When it fires, the key is marked
        as long-fired so the subsequent release is suppressed.
        """
        # Cancel any existing long timer for this key.
        existing = self._gesture_long_timers.get(key)
        if existing:
            existing.cancel()

        threshold_s = entry.get("long_ms", self._long_press_ms) / 1000.0

        def fire_long(key_=key, entry_=entry, ev_=event):
            if not self._active:
                return
            self._gesture_long_timers.pop(key_, None)
            self._gesture_long_fired.add(key_)
            # Also cancel any pending multipress timer.
            mt = self._gesture_timers.pop(key_, None)
            if mt:
                mt.cancel()
            self._gesture_counts.pop(key_, None)
            self._gesture_events.pop(key_, None)
            self._gesture_press_time.pop(key_, None)
            if self._debug:
                print(f"[gesture:{self.name}] key={key_} -> long (timer)")
            self._fire_sequence(entry_["long"], ev_)

        t = threading.Timer(threshold_s, fire_long)
        t.daemon = True
        t.start()
        self._gesture_long_timers[key] = t
        self._timer_list.append(t)

    def _start_repeat_timer(self, key, entry, event, initial=False,
                             repeat_ms_override=None):
        """
        Schedule the next repeat fire for key.

        On the initial call (initial=True) the delay is repeat_delay_ms
        (hold time before first repeat fires).  On subsequent calls the
        delay is repeat_ms (interval between repeats), unless
        repeat_ms_override is provided (used by the accel tier logic to
        apply the active tier's repeat_ms immediately).

        Each firing reschedules itself, so repeating continues until
        _cancel_repeat() is called on release.
        """
        existing = self._gesture_repeat_timers.pop(key, None)
        if existing:
            existing.cancel()

        delay_ms = (
            entry.get("repeat_delay_ms", self._repeat_delay_ms) if initial
            else (
                repeat_ms_override
                if repeat_ms_override is not None
                else entry.get("repeat_ms", self._repeat_ms)
            )
        )

        def fire_repeat(key_=key, entry_=entry, ev_=event):
            if not self._active:
                return
            self._gesture_repeat_timers.pop(key_, None)
            # If the key was already released, do nothing.
            if key_ not in self._gesture_press_time:
                return
            self._gesture_repeat_fired.add(key_)

            # ── Accel tier selection ──────────────────────────────────
            # Walk the sorted tiers and take the last one whose
            # after_ms threshold has been reached.  Tiers may override
            # the sequence, the next interval, or both; omitted keys
            # fall through to the lower tier or the base entry value.
            elapsed_ms = (
                time.time() - self._gesture_press_time[key_]
            ) * 1000
            accel = entry_.get("repeat_accel", [])
            active_seq = entry_["repeat"]
            next_ms    = None   # None → use entry_ / bankset default
            for tier in sorted(accel, key=lambda t: t["after_ms"]):
                if elapsed_ms >= tier["after_ms"]:
                    if "repeat" in tier:
                        active_seq = tier["repeat"]
                    if "repeat_ms" in tier:
                        next_ms = tier["repeat_ms"]
                else:
                    break   # tiers are ascending; none beyond this match

            if self._debug:
                if accel:
                    # Identify the deepest tier whose threshold has been
                    # crossed so the log shows exactly which tier is active.
                    active_tier = None
                    for _t in sorted(accel, key=lambda t: t["after_ms"]):
                        if elapsed_ms >= _t["after_ms"]:
                            active_tier = _t
                        else:
                            break
                    if active_tier:
                        seq_note = (
                            ", seq override" if "repeat" in active_tier else ""
                        )
                        tier_str = (
                            f"tier@{active_tier['after_ms']:.0f}ms{seq_note}"
                        )
                    else:
                        tier_str = "no tier"
                    # Show the interval that will be used for the NEXT timer.
                    if next_ms is not None:
                        ms_str = f"{next_ms:.0f}ms"
                    else:
                        ms_str = (
                            f"{entry_.get('repeat_ms', self._repeat_ms):.0f}ms"
                            f" (base)"
                        )
                    print(
                        f"[gesture:{self.name}] key={key_} -> repeat "
                        f"elapsed={elapsed_ms:.0f}ms "
                        f"{tier_str}, next={ms_str}"
                    )
                else:
                    print(
                        f"[gesture:{self.name}] key={key_} -> repeat"
                    )
            self._fire_sequence(active_seq, ev_)
            # Reschedule using the active tier's interval (if any).
            self._start_repeat_timer(key_, entry_, ev_, initial=False,
                                     repeat_ms_override=next_ms)

        t = threading.Timer(delay_ms / 1000.0, fire_repeat)
        t.daemon = True
        t.start()
        self._gesture_repeat_timers[key] = t
        self._timer_list.append(t)

    def _cancel_repeat(self, key):
        """Cancel any pending repeat timer for key and clear fired state."""
        t = self._gesture_repeat_timers.pop(key, None)
        if t:
            t.cancel()
        self._gesture_repeat_fired.discard(key)

    def _handle_gesture_release(self, key, entry, event):
        """
        Handle a release event for a gesture entry.

        Cancels any pending long or repeat timers.  Dispatches:
          - 'long' if hold exceeded long_ms (edge case: timer and release race)
          - 'single' on quick release if defined (and no multi pending)
          - starts multipress timer if double/triple defined
          - nothing if 'repeat' fired at least once (release just stops it)
        """
        # Cancel any running repeat timer -- key released.
        # Save the fired flag first since _cancel_repeat clears it.
        repeat_already_fired = key in self._gesture_repeat_fired
        self._cancel_repeat(key)

        press_time = self._gesture_press_time.pop(key, None)
        if press_time is None:
            return None

        has_long   = "long"   in entry
        has_repeat = "repeat" in entry
        has_multi  = "double" in entry or "triple" in entry

        if has_long:
            lt = self._gesture_long_timers.pop(key, None)
            if lt:
                lt.cancel()

            elapsed_ms = (time.time() - press_time) * 1000.0
            threshold  = entry.get("long_ms", self._long_press_ms)

            if elapsed_ms >= threshold:
                mt = self._gesture_timers.pop(key, None)
                if mt:
                    mt.cancel()
                self._gesture_counts.pop(key, None)
                self._gesture_events.pop(key, None)
                if self._debug:
                    print(
                        f"[gesture:{self.name}] key={key} "
                        f"elapsed={elapsed_ms:.0f}ms -> long"
                    )
                return self._execute_sequence(entry["long"], event)

            # Short press.
            if self._debug:
                print(
                    f"[gesture:{self.name}] key={key} "
                    f"elapsed={elapsed_ms:.0f}ms -> single/tap"
                )
            if not has_multi:
                self._gesture_counts.pop(key, None)
                self._gesture_events.pop(key, None)
                if "single" in entry and not entry.get("eager_single"):
                    return self._execute_sequence(entry["single"], event)
                return []
            self._reset_gesture_timer(key, entry, event)
            return []

        if has_repeat:
            repeat_fired = repeat_already_fired

            if not repeat_fired:
                # Quick tap before first repeat -- treat as single.
                if self._debug:
                    print(
                        f"[gesture:{self.name}] key={key} "
                        f"-> single (released before first repeat)"
                    )
                if not has_multi:
                    self._gesture_counts.pop(key, None)
                    self._gesture_events.pop(key, None)
                    if "single" in entry and not entry.get("eager_single"):
                        return self._execute_sequence(entry["single"], event)
                    return []
                self._reset_gesture_timer(key, entry, event)
            else:
                # At least one repeat fired; release silently stops it.
                self._gesture_counts.pop(key, None)
                self._gesture_events.pop(key, None)
            return []

        # No 'long' or 'repeat': release carries no action (timer handles it).
        return []

    def _reset_gesture_timer(self, key, entry, event):
        """
        Cancel any existing multipress window timer for key and start a
        new one.  When the timer fires it dispatches based on the
        accumulated press count.
        """
        existing = self._gesture_timers.pop(key, None)
        if existing:
            existing.cancel()

        def fire(key_=key, entry_=entry):
            if not self._active:
                return
            count = self._gesture_counts.pop(key_, 1)
            ev    = self._gesture_events.pop(key_, event)
            self._gesture_timers.pop(key_, None)
            self._gesture_press_time.pop(key_, None)
            label = {1: "single", 2: "double", 3: "triple"}.get(count)
            if self._debug:
                print(
                    f"[gesture:{self.name}] key={key_} "
                    f"count={count} -> {label}"
                )
            if label == "single" and entry_.get("eager_single"):
                pass    # already fired eagerly at press
            elif label and label in entry_:
                self._fire_sequence(entry_[label], ev)

        window_ms = entry.get("multi_ms", self._multi_press_window_ms)
        t = threading.Timer(window_ms / 1000.0, fire)
        t.daemon = True
        t.start()
        self._gesture_timers[key] = t
        self._timer_list.append(t)

    # ------------------------------------------------------------------
    # Trigger value matching
    # ------------------------------------------------------------------

    def _matches_trigger_value(self, entry, event):
        """Return True if the event's data value satisfies trigger_value."""
        tv = entry.get("trigger_value")
        if tv is None:
            return True
        if hasattr(event, 'value'):
            val = event.value
        elif hasattr(event, 'velocity'):
            val = event.velocity
        elif hasattr(event, 'program'):
            val = event.program
        else:
            return True
        return self._value_in_range(tv, val)

    @staticmethod
    def _value_in_range(spec, value):
        """
        Check whether value satisfies a trigger_value spec.

        Spec forms:
            int          -- exact match
            "64"         -- exact match
            "64-127"     -- inclusive range
            ">64"        -- greater than
            "<64"        -- less than
            ">=64"       -- greater than or equal
            "<=64"       -- less than or equal
            [spec, ...]  -- list of any of the above (OR logic)
        """
        if isinstance(spec, int):
            return value == spec
        if isinstance(spec, list):
            return any(BankSet._value_in_range(s, value) for s in spec)
        if isinstance(spec, str):
            s = spec.strip()
            try:
                if s.startswith(">="):
                    return value >= int(s[2:].strip())
                if s.startswith("<="):
                    return value <= int(s[2:].strip())
                if s.startswith(">"):
                    return value > int(s[1:].strip())
                if s.startswith("<"):
                    return value < int(s[1:].strip())
                if '-' in s:
                    lo, hi = s.split('-', 1)
                    return int(lo.strip()) <= value <= int(hi.strip())
                return value == int(s)
            except ValueError:
                return False
        return True

    # ------------------------------------------------------------------
    # Fast chord dismissal
    # ------------------------------------------------------------------

    @staticmethod
    def _is_fast_chord(fk):
        """Return True if all keys in the chord frozenset are CC or NOTE keys.

        Fast chords require all members to send a release signal (CC=0 or
        NoteOff).  When any member's release arrives before the chord is
        complete, the window is cancelled immediately and the fallback
        individual dispatch fires with near-zero latency.
        """
        return all(k.startswith("CC") or k.startswith("NOTE") for k in fk)

    def _maybe_dismiss_fast_chord(self, key, bank_name, bank, release_event):
        """
        Check whether key is a member of any pending fast chord.  If so,
        cancel the chord window and collect fallback events.

        release_event is the CC=0 or NoteOff event that triggered the
        dismissal.  For gesture keys it is used to complete both the press
        and release in one step, since the release is consumed here and
        will not arrive again.

        Returns a list of events (may be empty) if a fast chord was
        dismissed, or None if no fast chord was pending for this key.
        """
        chord_members = self._chord_members.get(bank_name, {})
        if key not in chord_members:
            return None

        immediate = []
        dismissed = False
        for fk in chord_members[key]:
            if not self._is_fast_chord(fk):
                continue
            pending = self._chord_pending.get(fk)
            if pending is None:
                continue

            pending["timer"].cancel()
            self._chord_pending.pop(fk)
            dismissed = True

            # Cancel any other pending chord windows sharing keys with
            # this one -- those keys are consumed by the dismissal.
            for other_fk in list(self._chord_pending.keys()):
                if other_fk & fk:
                    other = self._chord_pending.pop(other_fk)
                    other["timer"].cancel()
                    if self._debug:
                        print(
                            f"[chord:{self.name}] fast dismissal cancelled "
                            f"overlapping window {set(other_fk)}"
                        )

            if self._debug:
                print(
                    f"[chord:{self.name}] fast chord {set(fk)} dismissed "
                    f"by release of {key!r}, dispatching "
                    f"{pending['arrived']} individually"
                )

            for k, ev in pending["events"].items():
                etype = self._entry_types.get((bank_name, k))
                if etype is None:
                    immediate.append(ev)
                elif etype == "direct":
                    result = self._execute_sequence(bank[k], ev)
                    if result:
                        immediate.extend(result)
                elif etype == "toggle":
                    result = self._handle_toggle(k, bank[k], ev)
                    if result:
                        immediate.extend(result)
                elif etype == "gesture":
                    # We have both the stored press event (ev) and the
                    # release event that triggered the dismissal.  Handle
                    # both in sequence: set press state with back-dated
                    # time, then process the release immediately.
                    self._gesture_counts[k] = \
                        self._gesture_counts.get(k, 0) + 1
                    self._gesture_press_time[k] = pending["press_times"][k]
                    self._gesture_events[k]     = ev
                    result = self._handle_gesture_release(
                        k, bank[k], release_event
                    )
                    if result:
                        immediate.extend(result)

        if dismissed:
            return immediate
        return None

    def _dispatch_fallback_key(self, k, ev, press_times):
        """Dispatch a single key individually as a chord fallback."""
        bank_name = self.active_bank
        bank      = self.banks[bank_name]
        etype     = self._entry_types.get((bank_name, k))
        if etype is None:
            if self._active and self._output_fn is not None:
                self._output_fn(ev)
        elif etype == "direct":
            self._fire_sequence(bank[k], ev)
        elif etype == "toggle":
            result = self._handle_toggle(k, bank[k], ev)
            if result:
                for ev_out in result:
                    self._output_fn(ev_out)
        elif etype == "gesture":
            self._fire_sequence_gesture_fallback(
                k, bank[k], ev, press_times.get(k)
            )

    # ------------------------------------------------------------------
    # Chord
    # ------------------------------------------------------------------

    def _handle_chord_arrival(self, key, chord_key_sets, bank, event):
        """
        Called when a key that participates in at least one chord arrives.

        Standard chords (any non-CC/NOTE member): wait for chord_window_ms.
        Fast chords (all CC or NOTE members): _maybe_dismiss_fast_chord
        cancels the window early on any member release.

        If the window expires with an incomplete set, each arrived key is
        dispatched individually as a fallback.
        """
        for fk in chord_key_sets:
            pending = self._chord_pending.get(fk)

            if pending is None:
                # First key of this chord -- open the window.
                def make_expire(fk_=fk):
                    def expire():
                        if not self._active:
                            return
                        dropped = self._chord_pending.pop(fk_, None)
                        if dropped is None:
                            return
                        if self._debug:
                            print(
                                f"[chord:{self.name}] window expired, "
                                f"incomplete {set(fk_)}, dispatching "
                                f"{dropped['arrived']} individually"
                            )
                        # Cancel overlapping windows and collect their keys
                        # to avoid dispatching the same key twice.
                        already_dispatched = set()
                        for other_fk in list(self._chord_pending.keys()):
                            if other_fk & fk_:
                                other = self._chord_pending.pop(other_fk)
                                other["timer"].cancel()
                                # Keys in the other window that are NOT in
                                # this one would be orphaned -- dispatch them.
                                for k, ev in other["events"].items():
                                    if k not in dropped["events"]:
                                        already_dispatched.add(k)
                                        self._dispatch_fallback_key(
                                            k, ev, other["press_times"]
                                        )
                                if self._debug:
                                    print(
                                        f"[chord:{self.name}] expiry cancelled "
                                        f"overlapping window {set(other_fk)}"
                                    )
                        bank_ = self.banks[self.active_bank]
                        for k, ev in dropped["events"].items():
                            if k in already_dispatched:
                                continue
                            self._dispatch_fallback_key(
                                k, ev, dropped["press_times"]
                            )
                    return expire

                t = threading.Timer(
                    self._chord_window_ms / 1000.0, make_expire()
                )
                t.daemon = True
                t.start()
                self._timer_list.append(t)
                self._chord_pending[fk] = {
                    "arrived":     {key},
                    "timer":       t,
                    "events":      {key: event},
                    "press_times": {key: time.time()},
                }

            else:
                # Subsequent key within the window.
                pending["arrived"].add(key)
                pending["events"][key]      = event
                pending["press_times"][key] = time.time()

                if pending["arrived"] == fk:
                    # All keys arrived -- cancel the timer and fire.
                    pending["timer"].cancel()
                    self._chord_pending.pop(fk)

                    entry = None
                    for k in bank:
                        if isinstance(k, tuple) and frozenset(k) == fk:
                            entry = bank[k]
                            break
                    if entry is None:
                        return None

                    if self._debug:
                        print(f"[chord:{self.name}] complete: {set(fk)}")

                    # Cancel any other pending chord windows that share
                    # keys with this chord -- those keys are now consumed
                    # and must not be dispatched as fallbacks.
                    for other_fk in list(self._chord_pending.keys()):
                        if other_fk & fk:  # non-empty intersection
                            other = self._chord_pending.pop(other_fk)
                            other["timer"].cancel()
                            if self._debug:
                                print(
                                    f"[chord:{self.name}] cancelled "
                                    f"overlapping window {set(other_fk)}"
                                )

                    # Record chord keys as consumed so releases are suppressed.
                    self._chord_consumed.update(fk)

                    # Check if entry has double/triple -- if so, accumulate.
                    has_multi = "double" in entry or "triple" in entry
                    if has_multi:
                        self._handle_chord_multipress(fk, entry, event)
                        return []

                    # Return events directly to handle() -- do NOT call
                    # _output_fn here (deadlock risk in mididings callback).
                    if "single" in entry:
                        return self._execute_sequence(entry["single"], event)
                    return []

        return None

    def _handle_chord_multipress(self, fk, entry, event):
        """
        Accumulate repeated completions of the same chord within
        MULTI_PRESS_WINDOW_MS, then dispatch based on count.
        Works like gesture multi-press but keyed on the chord frozenset.
        Always dispatches via _output_fn (timer callback).
        """
        state = self._chord_counts.get(fk)
        if state is None:
            count = 1
        else:
            state["timer"].cancel()
            count = state["count"] + 1

        def fire(fk_=fk, entry_=entry, count_=count, ev_=event):
            if not self._active:
                return
            self._chord_counts.pop(fk_, None)
            label = {1: "single", 2: "double", 3: "triple"}.get(count_)
            if self._debug:
                print(
                    f"[chord:{self.name}] {set(fk_)} "
                    f"count={count_} -> {label}"
                )
            if label and label in entry_:
                self._fire_sequence(entry_[label], ev_)

        window_ms = entry.get("multi_ms", self._multi_press_window_ms)
        t = threading.Timer(window_ms / 1000.0, fire)
        t.daemon = True
        t.start()
        self._chord_counts[fk] = {"count": count, "timer": t}
        self._timer_list.append(t)

    def _fire_sequence_gesture_fallback(self, key, entry, event, press_time):
        """
        Dispatch a gesture entry from a chord fallback timer callback.
        Back-dates the press time if 'long' is defined so hold duration
        is measured from the original press, not the chord window expiry.
        """
        result = self._handle_gesture_press(key, entry, event)
        if result:
            for ev_out in result:
                self._output_fn(ev_out)
        # Back-date after _handle_gesture_press sets it to time.time()
        if press_time is not None and "long" in entry and \
           key in self._gesture_press_time:
            self._gesture_press_time[key] = press_time
