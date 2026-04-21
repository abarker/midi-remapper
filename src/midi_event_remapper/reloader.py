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
    interval_s : float
        Polling interval in seconds (default: 1.0).
    debug : bool
        If True, print extra diagnostic messages.
    """

    def __init__(self, paths, global_config, interval_s=POLL_INTERVAL,
                 debug=False):
        self._paths        = [Path(p) for p in paths]
        self._config       = global_config
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
            new_mtimes = self._current_mtimes()
            changed = [
                p for p in self._paths
                if new_mtimes.get(p) != self._last_mtimes.get(p)
            ]
            if changed:
                self._last_mtimes = new_mtimes
                self._reload(changed)

    # ------------------------------------------------------------------
    # Reload logic
    # ------------------------------------------------------------------

    def _reload(self, changed_paths):
        """Load all config files and swap BankSets if successful."""
        from midi_event_remapper.loader import load_bankset_file

        changed_names = ", ".join(p.name for p in changed_paths)
        print(f"\n[reload] {changed_names} changed, reloading...")

        new_banksets = self._try_load_all(load_bankset_file)
        if new_banksets is None:
            return   # Error already printed; keep current config.

        errors = []
        for bs in new_banksets:
            errors.extend(bs.validate())
        if errors:
            print("[reload] config errors -- keeping current config")
            for e in errors:
                print(f"  x {e}")
            return

        self._transfer_state(new_banksets)
        self._cancel_old_timers()

        # Atomic swap -- the GIL makes list assignment atomic enough here
        # because dispatcher.main_handler only reads the list, not mutates it.
        self._config.BANK_SETS = new_banksets

        preserved = [
            f"{bs.name}={bs.active_bank}" for bs in new_banksets
        ]
        print(f"[reload] {changed_names}: OK  "
              f"(active banks: {', '.join(preserved)})")

    def _try_load_all(self, load_fn):
        """Load all paths, retrying once after RETRY_DELAY_S on failure.

        Returns a flat list of BankSet instances, or None if loading fails.
        """
        for attempt in range(2):
            try:
                banksets = []
                for path in self._paths:
                    banksets.extend(load_fn(path))
                return banksets
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
            bs._output_fn  = old._output_fn
            bs._display_fn = old._display_fn
            # Preserve active bank only when it still exists in new config.
            if old.name in old_by_name and old.active_bank in bs.banks:
                bs.active_bank = old.active_bank

    def _cancel_old_timers(self):
        """Cancel all in-flight timers on the current BankSets."""
        for bs in self._config.BANK_SETS:
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
