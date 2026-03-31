"""
bankset.py

BankSet class: a named collection of MIDI event mapping banks.

This module has no mididings dependency.  All mididings interaction is
handled via the output_fn parameter (injected by dispatcher.py) and the
build_event / event_key functions imported from midi.py.

See the config.py module docstring for the full schema of bank entry
types and sequence item formats.
"""
import threading
import time

from midi_event_remapper.midi import build_event, event_key


class BankSet:
    """
    A named collection of banks.  One bank is active at a time.

    Each bank is a dict mapping event keys (strings or tuples of strings)
    to behaviour definitions.  The behaviour type is inferred from the
    shape of the value:

        List value             -> direct: fires immediately, no state
        Dict with a / b        -> toggle: alternates between two sequences
        Dict with tap / long   -> long press (momentary CC only):
                                  tap fires on quick release,
                                  long fires after long_ms; no window delay
        Dict with single /     -> multi-press: accumulates presses within
          double / triple         multi_press_window_ms, then dispatches;
                                  incurs a delay on every press
        Tuple key              -> chord: all keys must arrive within
                                  chord_window_ms; falls back to
                                  individual dispatch if incomplete

    Parameters
    ----------
    name : str
        Human-readable identifier, used in debug output.
    banks : dict
        Maps bank name strings to bank dicts.
    active_bank : str
        Name of the initially active bank.
    output_fn : callable or None
        Called with a single mididings event argument to emit output from
        timer callbacks.  Set to engine.output_event by dispatcher.py.
        Must be set before any timer-fired dispatch can occur.
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

    # Top-level dict keys that are config metadata, not action labels.
    _META_KEYS = frozenset({"debounce_ms", "long_ms"})

    def __init__(
        self,
        name,
        banks,
        active_bank           = "default",
        output_fn             = None,
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
        self._debug                 = debug
        self._data_offset           = data_offset
        self._debounce_ms           = debounce_ms
        self._multi_press_window_ms = multi_press_window_ms
        self._chord_window_ms       = chord_window_ms
        self._long_press_ms         = long_press_ms

        # Toggle state: key -> bool (False = state "a", True = state "b")
        # Persists across bank switches intentionally.
        self._toggle_states = {}   # key -> bool
        self._toggle_ts     = {}   # key -> float (last trigger time)

        # Multi-press state
        self._press_counts  = {}   # key -> int
        self._press_timers  = {}   # key -> Timer
        self._press_events  = {}   # key -> mididings event

        # Long-press state: key -> float (press timestamp)
        self._lp_starts     = {}

        # Chord state
        # frozenset -> {"arrived": set, "timer": Timer,
        #               "events":  {key: event},
        #               "press_times": {key: float}}
        self._chord_pending  = {}

        # Keys whose presses were consumed by a completed chord.
        # Their CC=0 releases are suppressed to prevent them firing
        # mappings in whatever bank is active at release time.
        self._chord_consumed = set()

        # Keep timer references alive until they fire.
        self._timer_list    = []

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
            print(f"[BankSet:{self.name}] bank: {self.active_bank!r} -> {name!r}")
        self.active_bank = name

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

        # Periodically remove dead timers to prevent unbounded growth.
        # Timer threads accumulate quickly with frequent chord attempts.
        if len(self._timer_list) > 50:
            self._cleanup_timers()

        # ── CC=0 release handling ──────────────────────────────────────
        if hasattr(event, 'value') and event.value == 0:
            # Suppress releases for keys consumed by a completed chord.
            # Without this, the release would fire mappings in whatever
            # bank became active after the chord switched banks.
            if key in self._chord_consumed:
                self._chord_consumed.discard(key)
                return []
            # Long-press release on a mapped longpress key.
            if (bank_name, key) in self._entry_types and \
               self._entry_types[(bank_name, key)] == "longpress":
                return self._handle_longpress_release(key, bank[key], event)
            # Fast chord dismissal: if this CC key is a member of any
            # pending fast chord, cancel the window and dispatch the
            # fallback immediately rather than waiting for the timeout.
            if self._maybe_dismiss_fast_chord(key, bank_name, bank):
                return []
            # CC=0 not consumed by any of the above.
            # If the key has a direct mapping, fall through to normal
            # dispatch so the release is remapped the same way as the
            # press (value is passed through via event_value in
            # _execute_sequence).  Otherwise pass through unchanged.
            etype = self._entry_types.get((bank_name, key))
            if etype != "direct":
                return None
            # fall through to normal single-key dispatch below

        # ── Chord participation ────────────────────────────────────────
        # If this key participates in any chord in the current bank, the
        # chord machinery takes ownership of the event.  If the chord
        # window expires without all keys arriving, the individual key
        # entry is dispatched as a fallback (see _handle_chord_arrival).
        # CC=0 release events are explicitly excluded: they are handled
        # above as long-press releases or fast-chord dismissals and must
        # never be treated as new chord presses.
        is_release = hasattr(event, 'value') and event.value == 0
        if not is_release and key in chord_members:
            self._handle_chord_arrival(key, chord_members[key], bank, event)
            return []   # event consumed by chord machinery; suppress pass-through

        # ── Normal single-key dispatch ─────────────────────────────────
        if key not in bank:
            return None

        etype = self._entry_types[(bank_name, key)]
        entry = bank[key]

        if etype == "direct":
            return self._execute_sequence(entry, event)
        elif etype == "toggle":
            return self._handle_toggle(key, entry, event)
        elif etype == "longpress":
            self._handle_longpress_press(key)
            return None   # nothing emitted until release
        elif etype == "multipress":
            self._handle_multipress(key, entry, event)
            return None   # always dispatched via timer

        return None

    def validate(self):
        """
        Check all bank entries for configuration errors.
        Returns a list of error strings; an empty list means no errors.
        Called at startup before run().
        """
        errors  = []
        pc_min  = self._data_offset
        pc_max  = 127 + self._data_offset

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
                        errors.append(
                            f"{ctx}[{i}]: malformed send {send!r}"
                        )
                elif send.startswith("CC"):
                    try:
                        n = int(send[2:])
                        if not (0 <= n <= 127):
                            errors.append(
                                f"{ctx}[{i}]: {send!r} CC number out of "
                                f"range (0-127)"
                            )
                    except ValueError:
                        errors.append(
                            f"{ctx}[{i}]: malformed send {send!r}"
                        )
                elif send.startswith("NOTE"):
                    try:
                        n = int(send[4:])
                        if not (0 <= n <= 127):
                            errors.append(
                                f"{ctx}[{i}]: {send!r} note number out of "
                                f"range (0-127)"
                            )
                    except ValueError:
                        errors.append(
                            f"{ctx}[{i}]: malformed send {send!r}"
                        )
                elif send != "SYSEX":
                    errors.append(
                        f"{ctx}[{i}]: unrecognised send {send!r}"
                    )

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
            elif etype == "longpress":
                for action in ("tap", "long"):
                    if action in value:
                        check_sequence(value[action], f"{ctx}[{action!r}]")
            elif etype in ("multipress", "chord"):
                for label in ("single", "double", "triple"):
                    if label in value:
                        check_sequence(
                            value[label], f"{ctx}[{label!r}]"
                        )

        for bank_name, bank in self.banks.items():
            for key, value in bank.items():
                check_entry(key, value, bank_name)

        if self.active_bank not in self.banks:
            errors.append(
                f"BankSet {self.name!r}: active_bank "
                f"{self.active_bank!r} not found in banks"
            )

        return errors

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _cleanup_timers(self):
        """Remove completed or cancelled timers from _timer_list.

        Each chord window, multipress window, and delayed send creates a
        threading.Timer (which is a thread).  Without cleanup, the list
        grows indefinitely with dead threads, eventually causing hangs.
        Called automatically from handle() when the list exceeds 50 entries.
        """
        self._timer_list = [t for t in self._timer_list if t.is_alive()]

    def _build_lookup_tables(self):
        for bank_name, bank in self.banks.items():
            self._chord_members[bank_name] = {}
            for key, value in bank.items():
                try:
                    etype = self._classify(key, value)
                except ValueError:
                    # Unclassifiable entry — store sentinel so validate()
                    # can report it cleanly rather than crashing __init__.
                    etype = "unknown"
                self._entry_types[(bank_name, key)] = etype
                if isinstance(key, tuple):
                    fk = frozenset(key)
                    for k in key:
                        self._chord_members[bank_name].setdefault(
                            k, []
                        ).append(fk)

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
            if action_keys <= {"tap", "long"}:
                return "longpress"
            if action_keys <= {"single", "double", "triple"}:
                return "multipress"
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
        BANK sends are executed inline (delay key is ignored for BANK).
        Returns a non-empty list or None.
        """
        immediate = []
        for item in seq:
            send  = item.get("send", "")
            delay = float(item.get("delay", 0.0))

            if send == "BANK":
                self.switch_bank(item["bank"])
                continue

            if item.get("press_only") and getattr(event, 'value', None) == 0:
                continue

            ev_out = build_event(item, event.port, event.channel,
                                  event_value=getattr(event, 'value', None))

            if delay <= 0:
                immediate.append(ev_out)
                if self._debug:
                    print(f"  [seq] -> immediate: {ev_out}")
            else:
                if self._debug:
                    print(f"  [seq] -> in {delay:.3f}s: {ev_out}")
                t = threading.Timer(
                    delay, self._output_fn, args=(ev_out,)
                )
                t.daemon = True
                t.start()
                self._timer_list.append(t)

        # Return immediate list even if empty. An empty list signals
        # "this event was handled, emit nothing" -- which drops the event.
        # Returning None would mean "not handled", causing pass-through.
        return immediate

    def _fire_sequence(self, seq, event):
        """
        Like _execute_sequence but routes all immediate events through
        self._output_fn.  Used from timer callbacks where returning a
        value to mididings is not possible.
        """
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
    # Long press
    # ------------------------------------------------------------------

    def _handle_longpress_press(self, key):
        """Record the press timestamp.  Dispatch happens on CC=0 release."""
        self._lp_starts[key] = time.time()
        if self._debug:
            print(f"[longpress:{self.name}] key={key} pressed")

    def _handle_longpress_release(self, key, entry, event):
        """Measure elapsed time since press and dispatch tap or long."""
        start = self._lp_starts.pop(key, None)
        if start is None:
            return None
        elapsed_ms = (time.time() - start) * 1000.0
        threshold  = entry.get("long_ms", self._long_press_ms)
        action     = "long" if elapsed_ms >= threshold else "tap"
        if self._debug:
            print(
                f"[longpress:{self.name}] key={key} "
                f"elapsed={elapsed_ms:.0f}ms -> {action}"
            )
        if action in entry:
            return self._execute_sequence(entry[action], event)
        return None

    # ------------------------------------------------------------------
    # Multi-press
    # ------------------------------------------------------------------

    def _handle_multipress(self, key, entry, event):
        """
        Accumulate presses within multi_press_window_ms then dispatch
        based on count.  Each new press resets the window timer.
        Always dispatches via self._output_fn (timer callback).
        """
        count = self._press_counts.get(key, 0) + 1
        self._press_counts[key] = count
        self._press_events[key] = event

        existing = self._press_timers.pop(key, None)
        if existing:
            existing.cancel()

        def fire(key_=key, entry_=entry):
            n   = self._press_counts.pop(key_, 1)
            ev  = self._press_events.pop(key_, event)
            self._press_timers.pop(key_, None)
            label = {1: "single", 2: "double", 3: "triple"}.get(n)
            if self._debug:
                print(
                    f"[multipress:{self.name}] key={key_} "
                    f"count={n} -> {label}"
                )
            if label and label in entry_:
                self._fire_sequence(entry_[label], ev)

        t = threading.Timer(self._multi_press_window_ms / 1000.0, fire)
        t.daemon = True
        t.start()
        self._press_timers[key] = t
        self._timer_list.append(t)

    # ------------------------------------------------------------------
    # Fast chord dismissal
    # ------------------------------------------------------------------

    @staticmethod
    def _is_fast_chord(fk):
        """Return True if all keys in the chord frozenset are CC keys.

        Fast chords require all members to be momentary CC buttons (sending
        CC=127 on press, CC=0 on release).  When any member's release arrives
        before the chord is complete, the chord window is cancelled immediately
        and the fallback individual dispatch fires with near-zero latency.
        """
        return all(k.startswith("CC") for k in fk)

    def _maybe_dismiss_fast_chord(self, key, bank_name, bank):
        """
        Check whether key is a member of any pending fast chord.  If so,
        cancel the chord window and dispatch the fallback immediately.

        Returns True if at least one fast chord was dismissed, False otherwise.
        Called on every CC=0 release that is not a longpress release.
        """
        chord_members = self._chord_members.get(bank_name, {})
        if key not in chord_members:
            return False

        dismissed = False
        for fk in chord_members[key]:
            if not self._is_fast_chord(fk):
                continue
            pending = self._chord_pending.get(fk)
            if pending is None:
                continue

            pending["timer"].cancel()
            self._chord_pending.pop(fk)

            if self._debug:
                print(
                    f"[chord:{self.name}] fast chord {set(fk)} dismissed "
                    f"by release of {key!r}, dispatching "
                    f"{pending['arrived']} individually"
                )

            # Dispatch each arrived key individually, same logic as the
            # standard chord expiry fallback.
            for k, ev in pending["events"].items():
                etype = self._entry_types.get((bank_name, k))
                if etype is None:
                    self._output_fn(ev)
                elif etype == "direct":
                    self._fire_sequence(bank[k], ev)
                elif etype == "toggle":
                    result = self._handle_toggle(k, bank[k], ev)
                    if result:
                        for ev_out in result:
                            self._output_fn(ev_out)
                elif etype == "longpress":
                    # Back-date the timestamp so hold duration is measured
                    # from the original press, not the dismissal time.
                    self._lp_starts[k] = pending["press_times"][k]
                elif etype == "multipress":
                    self._handle_multipress(k, bank[k], ev)

            dismissed = True
        return dismissed

    # ------------------------------------------------------------------
    # Chord
    # ------------------------------------------------------------------

    def _handle_chord_arrival(self, key, chord_key_sets, bank, event):
        """
        Called when a key that participates in at least one chord arrives.
        chord_key_sets is a list of frozensets, one per chord definition
        this key belongs to.

        Standard chords (any non-CC member): wait for chord_window_ms.
        If all keys arrive before the timer fires the chord dispatches
        immediately.  If the timer fires with an incomplete set, each
        arrived key is dispatched individually as a fallback.

        Fast chords (all CC members): the window timer still starts here,
        but _maybe_dismiss_fast_chord cancels it early when any member's
        CC=0 release arrives, giving near-zero latency for the fallback.

        Note: keys that are longpress type have their press timestamp
        back-dated to the original arrival time in the fallback, compensating
        for time spent waiting in the chord window.
        """
        for fk in chord_key_sets:
            pending = self._chord_pending.get(fk)

            if pending is None:
                # First key of this chord -- open the window.
                def make_expire(fk_=fk):
                    def expire():
                        dropped = self._chord_pending.pop(fk_, None)
                        if dropped is None:
                            return
                        if self._debug:
                            print(
                                f"[chord:{self.name}] window expired, "
                                f"incomplete {set(fk_)}, dispatching "
                                f"{dropped['arrived']} individually"
                            )
                        bank_ = self.banks[self.active_bank]
                        for k, ev in dropped["events"].items():
                            etype = self._entry_types.get(
                                (self.active_bank, k)
                            )
                            if etype is None:
                                # Not individually mapped -- pass through.
                                self._output_fn(ev)
                            elif etype == "direct":
                                self._fire_sequence(bank_[k], ev)
                            elif etype == "toggle":
                                result = self._handle_toggle(
                                    k, bank_[k], ev
                                )
                                if result:
                                    for ev_out in result:
                                        self._output_fn(ev_out)
                            elif etype == "longpress":
                                # Back-date the timestamp to the original
                                # press time so the hold duration is measured
                                # correctly when the CC=0 release arrives.
                                self._lp_starts[k] = dropped["press_times"][k]
                            elif etype == "multipress":
                                self._handle_multipress(k, bank_[k], ev)
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
                        return

                    if self._debug:
                        print(f"[chord:{self.name}] complete: {set(fk)}")

                    # Record all chord keys as consumed so their CC=0
                    # releases are suppressed in handle().
                    self._chord_consumed.update(fk)

                    # Chord multi-press is not yet implemented;
                    # only "single" is dispatched.
                    if "single" in entry:
                        self._fire_sequence(entry["single"], event)
