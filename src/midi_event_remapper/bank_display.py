"""bank_display.py

A small tkinter window that always shows the current active bank name
across all BankSets.  Intended for use during live performance so the
player can glance at it to confirm which bank is active.

The window runs in a **separate process** (bank_display_subprocess.py) so
that the tkinter mainloop and its GIL usage are completely isolated from
the main process.  This is the primary motivation for the subprocess
design: during bank switches, the Tk render thread was competing for the
GIL with the JACK RT callback, causing xruns.  Moving Tk to its own
process eliminates that GIL contention entirely.

Communication is one-way (main → display): JSON lines written to the
subprocess stdin.  A lightweight relay thread drains the internal deque
and writes to the pipe.  The RT-facing side of the interface is unchanged:
``display.update()`` is still a bare ``deque.append()``, a single
GIL-only C operation with no additional mutex.

Exit behaviour
--------------
If the user clicks Exit (or closes the titled window) inside the display
subprocess, the subprocess exits.  The relay thread detects the broken
pipe and calls ``os._exit(0)`` to terminate the main process, preserving
the previous behaviour where the Exit button killed the entire program.

If the main process calls ``display.stop()`` (normal shutdown), a sentinel
is sent through the deque → pipe → subprocess, which causes the Tk window
to destroy itself cleanly.  The relay thread exits normally without
calling ``os._exit``.

Usage
-----
    from midi_event_remapper.bank_display import BankDisplay
    display = BankDisplay()
    display.start()

    # Notify the display when a bank changes:
    display.update("actition", "drums")

    # Shut down cleanly when done:
    display.stop()
"""
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque


class BankDisplay:
    """Spawn and communicate with a separate bank-display subprocess.

    The public interface is identical to the previous in-process
    ``BankDisplay``: ``start()``, ``stop()``, ``update()``, and the
    ``current_bankset_name`` property.  No other module needs to change.

    Internally the Tk window lives in ``bank_display_subprocess.py``,
    which is launched as ``sys.executable -m
    midi_event_remapper.bank_display_subprocess``.  Updates travel as
    newline-delimited JSON arrays over the subprocess stdin pipe.
    """

    def __init__(self, no_titlebar=False):
        self._deque        = deque()
        self._no_titlebar  = no_titlebar
        self._proc         = None
        self._relay_thread = None
        self._running      = False
        # Name of the bankset whose update was most recently forwarded to
        # the subprocess.  Updated by the relay thread, read by the
        # reloader from its own thread -- a plain attribute write/read on
        # CPython is atomic enough for this purpose (same as before).
        self._displayed_bankset_name = None

    # ------------------------------------------------------------------
    # Public API (unchanged from the previous in-process implementation)
    # ------------------------------------------------------------------

    def start(self):
        """Spawn the display subprocess and start the relay thread."""
        self._running = True

        cmd = [
            sys.executable, "-m",
            "midi_event_remapper.bank_display_subprocess",
        ]
        if self._no_titlebar:
            cmd.append("--no-titlebar")

        self._proc = subprocess.Popen(
            cmd,
            stdin    = subprocess.PIPE,
            encoding = "utf-8",
            # stdout/stderr are inherited so subprocess errors are visible.
        )

        self._relay_thread = threading.Thread(
            target = self._relay_loop,
            name   = "BankDisplayRelay",
            daemon = True,
        )
        self._relay_thread.start()

    @property
    def current_bankset_name(self):
        """Name of the bankset currently forwarded to the display, or None."""
        return self._displayed_bankset_name

    def stop(self):
        """Signal the display to shut down cleanly.

        Appends a sentinel ``None`` to the deque.  The relay thread picks
        it up, closes the subprocess stdin (causing the subprocess to see
        EOF and destroy its Tk window), then exits.
        """
        self._running = False
        self._deque.append(None)  # sentinel

    def update(self, bankset_name, bank_name, style=None):
        """Notify the display of a bank change.  Safe to call from any thread,
        including the JACK RT callback.

        Parameters
        ----------
        bankset_name : str
        bank_name    : str
        style        : dict or None
            Same visual-style dict as before (keys: bg, fg, font_size,
            width, height).  Must be JSON-serialisable (str/int values),
            which all real style dicts already are.
        """
        self._deque.append((bankset_name, bank_name, style))

    # ------------------------------------------------------------------
    # Relay thread
    # ------------------------------------------------------------------

    def _relay_loop(self):
        """Drain the deque and forward messages to the subprocess over stdin.

        Runs in the BankDisplayRelay daemon thread.  This thread is *not*
        in the RT callback path -- the RT callback only calls
        ``deque.append()``.  Pipe writes release the GIL during the
        underlying syscall, which is strictly better for RT safety than
        the previous arrangement where the Tk thread's GIL usage was
        concurrent with the RT callback.
        """
        stdin = self._proc.stdin
        while True:
            if self._deque:
                item = self._deque.popleft()

                if item is None:
                    # Clean shutdown requested by the main process.
                    try:
                        stdin.close()
                    except OSError:
                        pass
                    return  # relay exits normally; do NOT call os._exit

                bankset_name, bank_name, style = item

                # Update the tracked name before writing so that if the
                # write fails we still reflect what we attempted to show.
                self._displayed_bankset_name = bankset_name

                line = json.dumps([bankset_name, bank_name, style]) + "\n"
                try:
                    stdin.write(line)
                    stdin.flush()
                except (BrokenPipeError, OSError):
                    # Subprocess exited before we did (user clicked Exit or
                    # closed the window).  Mirror the old behaviour: the
                    # display's Exit button kills the entire program.
                    os._exit(0)
            else:
                # No pending messages; sleep briefly to avoid busy-spinning.
                # 5 ms is imperceptible for a visual display and uses
                # negligible CPU.
                time.sleep(0.005)
