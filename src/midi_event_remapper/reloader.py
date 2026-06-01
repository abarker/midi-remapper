"""reloader.py

Live config file reloader for midi_event_remapper.

Watches one or more ``.py`` config files for modification and reloads them
on the fly while the program is running.  BankSet bank state (which bank is
currently active) is preserved across reloads when the bank name still
exists in the new config.  In-flight timers on the old BankSets are
cancelled cleanly before they are discarded.

The reloader polls file modification times at a configurable interval
(default: 1 second) using ``os.stat()``, requiring no extra dependencies.
A short retry delay guards against reading a partially-written file.
"""
import threading
import time
from pathlib import Path

RETRY_DELAY_S = 0.2   # Seconds to wait before retrying a failed parse.
POLL_INTERVAL = 1.0   # Default poll interval in seconds.


class ConfigReloader:
    """Poll config files for changes and hot-swap BankSets on reload.

    All files that were originally passed on the command line are reloaded
    together whenever any one of them changes, since they collectively
    define the full set of BankSets.

    Parameters
    ----------
    paths : list[str | Path]
        Config files to watch.
    global_config : module
        The ``midi_event_remapper.config`` module.  Its ``BANK_SETS``
        attribute is replaced atomically on each successful reload.
    display : BankDisplay or None
        The active bank display window, if any.  Used to push a single
        targeted style update after a reload rather than updating every
        BankSet (which would leave the display on whichever bankset is
        last in the config list).
    interval_s : float
        Polling interval in seconds (default: 1.0).
    debug : bool
        If True, print extra diagnostic messages.
    """

    def __init__(self, paths, global_config, display=None,
                 interval_s=POLL_INTERVAL, debug=False):
        self._paths        = [Path(p) for p in paths]
        self._config       = global_config
        self._display      = display
        self._interval_s   = interval_s
        self._debug        = debug
        self._stop         = threading.Event()
        self._thread       = None
        self._last_mtimes  = self._current_mtimes()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self):
        """Start the background polling thread."""
        self._thread = threading.Thread(
            target = self._watch,
            name   = "ConfigReloader",
            daemon = True,
        )
        self._thread.start()

    def stop(self):
        """Signal the polling thread to stop and wait for it to exit."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_s + 1)

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _watch(self):
        """Poll for mtime changes and trigger reloads (runs in background)."""
        while not self._stop.wait(self._interval_s):
            try:
                new_mtimes = self._current_mtimes()
                changed = [
                    p for p in self._paths
                    if new_mtimes.get(p) != self._last_mtimes.get(p)
                ]
                if changed:
                    self._last_mtimes = new_mtimes
                    self._reload(changed)
            except Exception as e:
                # Never let an unexpected error kill the reloader thread.
                print(f"[reload] ERROR in watcher: {e}")

    # ------------------------------------------------------------------
    # Reload logic
    # ------------------------------------------------------------------

    def _reload(self, changed_paths):
        """Load all config files and swap BankSets if successful."""
        from midi_event_remapper.loader import load_bankset_file

        changed_names = ", ".join(p.name for p in changed_paths)
        print(f"\n[reload] {changed_names} changed, reloading...")

        load_result = self._try_load_all(load_bankset_file)
        if load_result is None:
            return   # Error already printed; keep current config.
        new_settings, new_banksets = load_result

        errors = []
        for bs in new_banksets:
            errs, warns = bs.validate()
            errors.extend(errs)
            for w in warns:
                print(f"[reload] warning: {w}")
        if errors:
            print("[reload] config errors -- keeping current config")
            for e in errors:
                print(f"  x {e}")
            return

        self._transfer_state(new_banksets)

        # Capture old BankSets before the swap so _cancel_old_timers()
        # still has a reference to them after BANK_SETS is replaced.
        # The swap must come first: once main_handler points to new_banksets
        # it will never call handle() on the old BankSets again, so
        # cancel_timers() has exclusive access to the old state with no
        # risk of a concurrent handle() interleaving with it.
        old_banksets = list(self._config.BANK_SETS)
        self._config.BANK_SETS = new_banksets
        self._cancel_old_timers(old_banksets)

        # Apply global settings from the reloaded config.  "debug" changes
        # config.DEBUG, making dispatcher-level debug hot-reloadable.
        # The CLI --debug / --no-debug flags are not re-applied here; they
        # are only set once at startup in cli.py and take permanent precedence.
        if "debug" in new_settings:
            self._config.DEBUG = new_settings["debug"]

        # Push one targeted display update so style changes take effect
        # immediately.  Pushing for every BankSet would leave the display
        # on whichever bankset happens to be last in the config list.
        self._refresh_display(new_banksets)

        preserved = [
            f"{bs.name}={bs.active_bank}" for bs in new_banksets
        ]
        print(f"[reload] {changed_names}: OK  "
              f"(active banks: {', '.join(preserved)})")

    def _refresh_display(self, new_banksets):
        """Push one display update for the bankset currently being shown.

        Chooses the target bankset in priority order:

        1. The bankset whose name matches what is currently on screen (so
           a reload that only changes colours stays on the same bankset).
        2. The first bankset that has more than one bank (the "main"
           multi-bank controller mapping).
        3. The first bankset in the list.
        """
        if self._display is None:
            return

        current = self._display.current_bankset_name
        target = next(
            (bs for bs in new_banksets if bs.name == current), None
        )
        if target is None:
            target = next(
                (bs for bs in new_banksets if len(bs.banks) > 1), None
            )
        if target is None and new_banksets:
            target = new_banksets[0]

        if target is not None:
            style = target._display_styles.get(target.active_bank)
            self._display.update(target.name, target.active_bank, style)

    def _try_load_all(self, load_fn):
        """Load all paths, retrying once after RETRY_DELAY_S on failure.

        Returns ``(merged_settings, banksets)`` on success, or ``None`` on
        failure.  Settings dicts from multiple files are merged left-to-right
        (later files win).
        """
        for attempt in range(2):
            try:
                merged   = {}
                banksets = []
                for path in self._paths:
                    result = load_fn(path)
                    merged.update(result.settings)
                    banksets.extend(result.banksets)
                return merged, banksets
            except (ValueError, SyntaxError, FileNotFoundError) as e:
                if attempt == 0:
                    # File may still be mid-write; wait and retry once.
                    if self._debug:
                        print(f"[reload] parse failed, retrying in "
                              f"{RETRY_DELAY_S*1000:.0f}ms...")
                    time.sleep(RETRY_DELAY_S)
                else:
                    print("[reload] parse error -- keeping current config")
                    print(f"  {e}")
                    return None

    def _transfer_state(self, new_banksets):
        """Copy output_fn, display_fn, and active bank from old BankSets.

        Matches old and new BankSets by name.  If a new BankSet has no
        name match, it inherits output_fn / display_fn from the first old
        BankSet so it can still emit events.
        """
        old_by_name  = {bs.name: bs for bs in self._config.BANK_SETS}
        fallback_old = next(iter(old_by_name.values()), None)

        for bs in new_banksets:
            old = old_by_name.get(bs.name, fallback_old)
            if old is None:
                continue
            bs._output_fn     = old._output_fn
            bs._display_fn    = old._display_fn
            # display_styles comes from the new config; do not overwrite it.
            # Preserve active bank only when names matched AND the bank
            # still exists in the new config.  The fallback_old path (name
            # mismatch) must never overwrite the new BankSet's active bank.
            if bs.name in old_by_name and old.active_bank in bs.banks:
                bs.active_bank = old.active_bank

    def _cancel_old_timers(self, old_banksets):
        """Cancel all in-flight timers on the old BankSets."""
        for bs in old_banksets:
            bs.cancel_timers()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_mtimes(self):
        """Return a dict of path -> mtime (or None if the file is missing)."""
        result = {}
        for p in self._paths:
            try:
                result[p] = p.stat().st_mtime
            except OSError:
                result[p] = None
        return result
