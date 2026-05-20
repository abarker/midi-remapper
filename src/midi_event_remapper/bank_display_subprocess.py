"""bank_display_subprocess.py

Subprocess entry point for the bank display window.

This module is launched by ``BankDisplay.start()`` as::

    sys.executable -m midi_event_remapper.bank_display_subprocess [--no-titlebar]

It reads newline-delimited JSON arrays from stdin::

    ["bankset_name", "bank_name", {"bg": "#1a2e1a", "font_size": 72}]
    ["bankset_name", "bank_name", null]

and renders them in a tkinter window.  A ``None`` / null style falls back
to module-level defaults.

Shutdown protocol
-----------------
* **User closes window** (Exit menu item or title-bar X button): the Tk
  window is destroyed, ``mainloop()`` returns, and the subprocess exits
  normally.  The parent's relay thread detects the closed pipe (via
  ``proc.poll()`` or a ``BrokenPipeError`` on the next write) and stops
  silently.  The main MIDI program keeps running.

* **Main process shuts down** (``display.stop()`` called in the
  ``finally`` block of ``cli.py``): the relay thread closes the stdin
  pipe, this subprocess sees EOF, appends a sentinel to its internal
  deque, and the Tk poll callback destroys the window.  The subprocess
  then exits normally.
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import threading
from collections import deque
from pathlib import Path

import tkinter as tk


# ---------------------------------------------------------------------------
# Visual defaults (identical to the previous bank_display.py)
# ---------------------------------------------------------------------------

DEFAULT_BG        = "#1a1a1a"
DEFAULT_FG        = "#ffffff"
DEFAULT_FONT_SIZE = 72

FONT_BANKSET = ("Helvetica", 14)
FONT_BANK    = ("Helvetica", DEFAULT_FONT_SIZE, "bold")
WINDOW_TITLE = "Bank Display"
POLL_MS      = 50   # How often the Tk event loop checks the queue (ms).


# ---------------------------------------------------------------------------
# Window class
# ---------------------------------------------------------------------------

class _BankDisplayWindow:
    """Tk window driven by JSON lines read from stdin.

    Intended to be instantiated and run from ``__main__`` only.
    """

    def __init__(self, no_titlebar: bool = False, save_pos: str | None = None):
        self._deque       = deque()
        self._no_titlebar = no_titlebar
        self._save_pos    = save_pos   # path string, or None
        self._last_pos    = None       # most recent "+X+Y" from <Configure>

        # Tk objects -- created in run(), referenced in callbacks.
        self._root          = None
        self._frame         = None
        self._bank_label    = None
        self._bankset_label = None
        self._bankset_var   = None
        self._bank_var      = None

        # Drag state for borderless window.
        self._drag_x = 0
        self._drag_y = 0

    # ------------------------------------------------------------------
    # Position persistence
    # ------------------------------------------------------------------

    def _on_configure(self, event):
        """Cache the window position whenever the WM moves or resizes it.

        Bound to ``<Configure>`` on the root window.  Keeping a running
        cache means ``_save_position`` never needs to call back into
        tkinter at shutdown time, which is important because signal
        handlers (SIGTERM, SIGINT) interrupt ``mainloop()`` and leave
        Tcl in a re-entrant state where geometry queries silently fail.
        """
        geom = self._root.geometry()   # "WxH+X+Y"
        m = re.search(r'([+-]\d+[+-]\d+)$', geom)
        if m:
            self._last_pos = m.group(1)

    def _save_position(self):
        """Write the cached window position to self._save_pos.

        Uses ``self._last_pos`` (maintained by ``_on_configure``) rather
        than querying tkinter, so it is safe to call from a signal handler
        or any other context where the Tk event loop is not running.
        """
        if not self._save_pos or not self._last_pos:
            return
        try:
            path = Path(self._save_pos)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._last_pos)
        except Exception:
            pass

    def _restore_position(self):
        """Apply a previously saved position to the window.

        Called once during startup, before ``mainloop()``.  Does nothing
        if the file does not exist (first run) or contains invalid data.
        Also primes ``self._last_pos`` so that an immediate save after
        restore (e.g. a very quick exit before the window is moved)
        writes a sensible value.
        """
        if not self._save_pos:
            return
        try:
            pos = Path(self._save_pos).read_text().strip()
            if re.fullmatch(r'[+-]\d+[+-]\d+', pos):
                self._root.geometry(pos)
                self._last_pos = pos   # prime the cache
        except FileNotFoundError:
            pass   # expected on first run
        except Exception:
            pass

    def _setup_signals(self):
        """Register handlers for SIGTERM and SIGINT that save position and exit.

        SIGTERM covers ``kill <pid>`` directed at the subprocess.
        SIGINT covers the rare case where the signal reaches the subprocess
        directly rather than being converted to a KeyboardInterrupt by Python
        (e.g. a second Ctrl+C while the first is already being handled).
        The normal Ctrl+C path is handled by the try/except in ``_run_tk``.
        SIGKILL cannot be caught -- position will not be saved in that case.
        """
        def _handler(signum, frame):
            self._save_position()
            sys.exit(0)
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (OSError, ValueError):
                pass   # signal cannot be set in some interpreter states

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        """Build the Tk window, start the stdin reader, run the mainloop.

        Returns when the mainloop exits for any reason (user closed the
        window, or parent sent a clean-shutdown sentinel via EOF).
        """
        self._start_stdin_reader()
        self._run_tk()

    # ------------------------------------------------------------------
    # Stdin reader (runs in its own daemon thread)
    # ------------------------------------------------------------------

    def _start_stdin_reader(self):
        t = threading.Thread(
            target = self._stdin_reader,
            name   = "StdinReader",
            daemon = True,
        )
        t.start()

    def _stdin_reader(self):
        """Read JSON lines from stdin and enqueue them.

        Runs until EOF (pipe closed by parent) or an I/O error.  On exit,
        appends a ``None`` sentinel so the Tk poll loop destroys the window.
        """
        try:
            for raw in sys.stdin:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    # Malformed line -- ignore rather than crash.
                    continue
                self._deque.append(msg)
        except Exception:
            pass
        finally:
            # EOF or error: signal the Tk thread to tear down the window.
            self._deque.append(None)

    # ------------------------------------------------------------------
    # Tk setup
    # ------------------------------------------------------------------

    def _run_tk(self):
        """Build and run the Tk window in the calling thread."""
        root = tk.Tk()
        self._root = root

        root.title(WINDOW_TITLE)
        root.configure(bg=DEFAULT_BG)
        root.attributes("-topmost", True)
        root.resizable(True, True)

        # Keep _last_pos current so _save_position() never needs to
        # call back into tkinter (unsafe from signal handlers).
        root.bind("<Configure>", self._on_configure)

        if self._no_titlebar:
            root.overrideredirect(True)

        self._bankset_var = tk.StringVar(value="")
        self._bank_var    = tk.StringVar(value="---")

        # BankSet name in small text at top.
        bankset_label = tk.Label(
            root,
            textvariable = self._bankset_var,
            font         = FONT_BANKSET,
            bg           = DEFAULT_BG,
            fg           = "#888888",
            pady         = 4,
        )
        bankset_label.pack(fill=tk.X)

        # Bank name in large text.
        frame = tk.Frame(root, bg=DEFAULT_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        bank_label = tk.Label(
            frame,
            textvariable = self._bank_var,
            font         = FONT_BANK,
            bg           = DEFAULT_BG,
            fg           = DEFAULT_FG,
            padx         = 30,
            pady         = 20,
        )
        bank_label.pack(fill=tk.BOTH, expand=True)

        self._frame         = frame
        self._bank_label    = bank_label
        self._bankset_label = bankset_label

        if self._no_titlebar:
            self._bind_context_menu(root, bankset_label, frame, bank_label)
            self._bind_drag(root, bankset_label, frame, bank_label)
        else:
            root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_signals()
        self._restore_position()
        root.update_idletasks()   # let the WM process the geometry request
        root.after(POLL_MS, self._poll)
        try:
            root.mainloop()
        except KeyboardInterrupt:
            # Ctrl+C in the parent process sends SIGINT to the whole process
            # group.  Catch it here so the subprocess exits cleanly rather
            # than printing a traceback, saving position on the way out.
            self._save_position()
            try:
                root.destroy()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Bindings for borderless window
    # ------------------------------------------------------------------

    def _bind_context_menu(self, *widgets):
        """Bind right-click context menu to each widget."""
        menu = tk.Menu(self._root, tearoff=0)
        menu.add_command(label="Exit",   command=self._exit_program)
        menu.add_separator()
        menu.add_command(label="Cancel", command=menu.unpost)

        def _show(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        for widget in widgets:
            widget.bind("<Button-3>", _show)

    def _bind_drag(self, *widgets):
        """Bind left-button drag so the borderless window can be moved."""
        def _start(event):
            self._drag_x = event.x_root - self._root.winfo_x()
            self._drag_y = event.y_root - self._root.winfo_y()

        def _drag(event):
            self._root.geometry(
                f"+{event.x_root - self._drag_x}"
                f"+{event.y_root - self._drag_y}"
            )

        for widget in widgets:
            widget.bind("<Button-1>", _start)
            widget.bind("<B1-Motion>", _drag)

    # ------------------------------------------------------------------
    # Exit handlers
    # ------------------------------------------------------------------

    def _exit_program(self):
        """Exit menu item: destroy the window and let the subprocess exit."""
        self._save_position()
        self._root.destroy()

    def _on_close(self):
        """WM_DELETE_WINDOW handler for titled mode."""
        self._save_position()
        self._root.destroy()

    # ------------------------------------------------------------------
    # Deque poll (runs in Tk event loop via after())
    # ------------------------------------------------------------------

    def _poll(self):
        """Drain pending updates and reschedule."""
        while self._deque:
            item = self._deque.popleft()
            if item is None:
                # Sentinel: EOF from parent or stdin error.  Tear down.
                self._save_position()
                self._root.destroy()
                return
            bankset_name, bank_name, style = item
            self._apply_update(bankset_name, bank_name, style)

        self._root.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------
    # Visual update
    # ------------------------------------------------------------------

    def _apply_update(self, bankset_name, bank_name, style):
        """Apply a bank change to the Tk widgets."""
        style = style or {}
        bg        = style.get("bg",        DEFAULT_BG)
        fg        = style.get("fg",        DEFAULT_FG)
        font_size = style.get("font_size", DEFAULT_FONT_SIZE)

        self._bankset_var.set(bankset_name)
        self._bank_var.set(bank_name)

        self._root.configure(bg=bg)
        self._frame.configure(bg=bg)
        self._bank_label.configure(
            bg   = bg,
            fg   = fg,
            font = (FONT_BANK[0], font_size, FONT_BANK[2]),
        )
        self._bankset_label.configure(bg=bg)

        if "width" in style or "height" in style:
            w = style.get("width",  self._root.winfo_width())
            h = style.get("height", self._root.winfo_height())
            self._root.geometry(f"{w}x{h}")


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Bank display subprocess (not intended for direct use).",
    )
    parser.add_argument(
        "--no-titlebar",
        action = "store_true",
        dest   = "no_titlebar",
        help   = "Remove OS window decoration.",
    )
    parser.add_argument(
        "--save-pos",
        default = None,
        dest    = "save_pos",
        metavar = "FILE",
        help    = "File path for saving and restoring window position.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args   = _parse_args()
    window = _BankDisplayWindow(
        no_titlebar = args.no_titlebar,
        save_pos    = args.save_pos,
    )
    window.run()
    # Exit normally regardless of why the window closed.  The parent's
    # relay thread will detect the closed pipe via proc.poll() or a
    # BrokenPipeError on the next write, and will stop silently without
    # affecting the main MIDI program.
