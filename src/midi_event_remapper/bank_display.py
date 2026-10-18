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

Exit behavior
--------------
The display is **optional**.  Closing its window (or clicking Exit inside
it) does *not* affect the main program -- the relay thread simply stops
when it detects the subprocess has gone, and MIDI processing continues
uninterrupted.

If the main process calls ``display.stop()`` (its normal ``finally``
shutdown path), a sentinel is sent through the deque → pipe → subprocess,
which causes the Tk window to destroy itself cleanly.

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

    The display is optional: if the user closes the window the relay
    thread exits silently and the main program keeps running.
    """

    def __init__(self, no_titlebar=False, save_pos=None):
        self._deque        = deque()
        self._no_titlebar  = no_titlebar
        self._save_pos     = save_pos
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
        if self._save_pos:
            cmd.extend(["--save-pos", self._save_pos])

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

        Appends a sentinel ``None`` to the deque.  If the relay thread is
        still running it will pick it up, close the subprocess stdin
        (causing the subprocess to see EOF and destroy its Tk window), and
        exit.  If the subprocess has already gone (user closed the window),
        the sentinel is a no-op.
        """
        self._running = False
        self._deque.append(None)  # sentinel

    def update(self, bankset_name, bank_name, style=None):
        """Notify the display of a bank change.  Safe to call from any thread,
        including the JACK RT callback.

        If the display subprocess has already exited (user closed it), the
        message is silently discarded by the relay thread.

        Parameters
        ----------
        bankset_name : str
        bank_name    : str
        style        : dict or None
            Same visual-style dict as before (keys: bg, fg, font_size,
            width, height).  Must be JSON-serializable (str/int values),
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

        Exits silently whenever the subprocess disappears (user closed the
        window, subprocess crashed) or when the main process sends the
        shutdown sentinel via ``stop()``.  Either way the main program is
        not affected.
        """
        stdin = self._proc.stdin
        while True:
            if self._deque:
                item = self._deque.popleft()

                if item is None:
                    # Shutdown sentinel from stop(): close the pipe so the
                    # subprocess sees EOF and tears down its Tk window.
                    try:
                        stdin.close()
                    except OSError:
                        pass
                    try:
                        self._proc.wait(timeout=2.0)
                    except Exception:
                        pass
                    return

                bankset_name, bank_name, style = item

                # Update the tracked name before writing so that if the
                # write fails we still reflect what we attempted to show.
                self._displayed_bankset_name = bankset_name

                line = json.dumps([bankset_name, bank_name, style]) + "\n"
                try:
                    stdin.write(line)
                    stdin.flush()
                except (BrokenPipeError, OSError):
                    # Subprocess exited (user closed the window, or it
                    # crashed).  The display is optional -- just stop the
                    # relay and let the main program continue.
                    try:
                        self._proc.wait(timeout=1.0)
                    except Exception:
                        pass
                    return

            else:
                # No pending messages.  Check whether the subprocess is
                # still alive so we detect user-initiated close even when
                # no bank changes are in flight -- without this, a
                # BrokenPipeError would only surface on the next write,
                # which might be arbitrarily far in the future.
                if self._proc.poll() is not None:
                    # Subprocess has already exited; nothing left to do.
                    return
                # Sleep briefly to avoid busy-spinning.  5 ms is
                # imperceptible for a visual display and uses negligible CPU.
                time.sleep(0.005)
