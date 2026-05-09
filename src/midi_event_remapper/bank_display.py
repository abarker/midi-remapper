"""bank_display.py

A small tkinter window that always shows the current active bank name
across all BankSets.  Intended for use during live performance so the
player can glance at it to confirm which bank is active.

The window runs in its own thread and is updated via a thread-safe queue.
It stays on top of other windows so it remains visible while playing.

The update queue uses ``collections.deque`` rather than ``queue.Queue``
so that ``display.update()`` (called from within the mididings JACK RT
callback when using ``--jack-rt``) does not acquire a threading.Lock.
``deque.append`` is a single GIL-protected C operation with no additional
mutex, removing the deadlock/block risk in the RT path.

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
import os
import threading
from collections import deque
import tkinter as tk


DEFAULT_BG       = "#1a1a1a"
DEFAULT_FG       = "#ffffff"
DEFAULT_FONT_SIZE = 72        # Default bank-name font size in points.

FONT_BANKSET = ("Helvetica", 14)
FONT_BANK    = ("Helvetica", DEFAULT_FONT_SIZE, "bold")
WINDOW_TITLE = "Bank Display"
POLL_MS      = 50   # How often the Tk event loop checks the queue (ms).


class BankDisplay:
    """Thread-safe bank name display window.

    The tkinter mainloop runs in a dedicated daemon thread so it does not
    block the mididings event loop.  Bank updates are sent via a queue and
    processed by the Tk thread on its next poll cycle.

    When ``no_titlebar`` is True the OS window decoration is removed and a
    right-click context menu is provided in its place, with options to
    cancel (dismiss the menu) or exit the program entirely.

    Visual style (colours, font size, window dimensions) is controlled
    per-bank via the ``style`` argument to :meth:`update`.  Any key
    omitted from the style dict falls back to the module-level defaults.
    """

    def __init__(self, no_titlebar=False):
        self._deque        = deque()
        self._thread       = None
        self._root         = None
        self._running      = False
        self._no_titlebar           = no_titlebar
        self._drag_x                = 0
        self._drag_y                = 0
        self._displayed_bankset_name = None  # name of the bankset currently shown

        # Tk StringVars -- created in the Tk thread, stored here for access.
        self._bankset_var   = None
        self._bank_var      = None
        self._frame         = None
        self._bank_label    = None
        self._bankset_label = None

    def start(self):
        """Start the display window in a background thread."""
        self._running = True
        self._thread  = threading.Thread(
            target = self._run_tk,
            name   = "BankDisplay",
            daemon = True,
        )
        self._thread.start()

    @property
    def current_bankset_name(self):
        """Name of the bankset currently shown in the window, or None."""
        return self._displayed_bankset_name

    def stop(self):
        """Close the window and stop the background thread."""
        self._running = False
        self._deque.append(None)  # Sentinel picked up by next _poll cycle.

    def update(self, bankset_name, bank_name, style=None):
        """Notify the display of a bank change.  Safe to call from any thread.

        Parameters
        ----------
        bankset_name : str
            The name of the BankSet that changed.
        bank_name : str
            The new active bank name.
        style : dict or None
            Optional visual style for this bank.  Recognised keys:

            ``bg``         -- background colour string (e.g. ``"#1a2e1a"``)
            ``fg``         -- foreground (text) colour string
            ``font_size``  -- bank-name font size in points (int)
            ``width``      -- window width in pixels (int)
            ``height``     -- window height in pixels (int)

            Omitted keys fall back to the module-level defaults.
        """
        self._deque.append((bankset_name, bank_name, style))

    # ------------------------------------------------------------------
    # Tk thread
    # ------------------------------------------------------------------

    def _run_tk(self):
        """Build and run the Tk window (called in the background thread)."""
        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._root.configure(bg=DEFAULT_BG)
        self._root.attributes("-topmost", True)
        self._root.resizable(True, True)

        if self._no_titlebar:
            self._root.overrideredirect(True)

        self._bankset_var = tk.StringVar(value="")
        self._bank_var    = tk.StringVar(value="---")

        # BankSet name in small text at top.
        bankset_label = tk.Label(
            self._root,
            textvariable = self._bankset_var,
            font         = FONT_BANKSET,
            bg           = DEFAULT_BG,
            fg           = "#888888",
            pady         = 4,
        )
        bankset_label.pack(fill=tk.X)

        # Bank name in large text.
        self._frame = tk.Frame(self._root, bg=DEFAULT_BG)
        self._frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        bank_label = tk.Label(
            self._frame,
            textvariable = self._bank_var,
            font         = FONT_BANK,
            bg           = DEFAULT_BG,
            fg           = DEFAULT_FG,
            padx         = 30,
            pady         = 20,
        )
        bank_label.pack(fill=tk.BOTH, expand=True)
        self._bank_label    = bank_label
        self._bankset_label = bankset_label

        if self._no_titlebar:
            self._bind_context_menu(
                self._root, bankset_label, self._frame, bank_label
            )
            self._bind_drag(
                self._root, bankset_label, self._frame, bank_label
            )
        else:
            self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._root.after(POLL_MS, self._poll)
        self._root.mainloop()

    def _bind_context_menu(self, *widgets):
        """Bind the right-click context menu to each supplied widget."""
        menu = tk.Menu(self._root, tearoff=0)
        menu.add_command(label="Exit", command=self._exit_program)
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
        """Bind left-button drag so the borderless window can be repositioned."""
        def _start(event):
            self._drag_x = event.x_root - self._root.winfo_x()
            self._drag_y = event.y_root - self._root.winfo_y()

        def _drag(event):
            self._root.geometry(
                f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}"
            )

        for widget in widgets:
            widget.bind("<Button-1>", _start)
            widget.bind("<B1-Motion>", _drag)

    def _exit_program(self):
        """Exit the entire program from the display window."""
        os._exit(0)

    # ------------------------------------------------------------------
    # Queue / update helpers
    # ------------------------------------------------------------------

    def _poll(self):
        """Drain the deque of pending updates and reschedule.

        Also checks whether the main thread is still alive -- if it has
        exited (program finished or crashed), the window closes itself.
        """
        main = threading.main_thread()
        if not main.is_alive():
            self._root.destroy()
            return

        while self._deque:
            item = self._deque.popleft()
            if item is None:
                self._root.destroy()
                return
            bankset_name, bank_name, style = item
            self._apply_update(bankset_name, bank_name, style)
        if self._running:
            self._root.after(POLL_MS, self._poll)

    def _apply_update(self, bankset_name, bank_name, style):
        """Apply a bank change to the Tk widgets, using style for visual settings.

        Each key in style is applied only when present; absent keys fall back
        to module-level defaults so partial style dicts work correctly.
        """
        style = style or {}
        bg        = style.get("bg",        DEFAULT_BG)
        fg        = style.get("fg",        DEFAULT_FG)
        font_size = style.get("font_size", DEFAULT_FONT_SIZE)

        self._displayed_bankset_name = bankset_name
        self._bankset_var.set(bankset_name)
        self._bank_var.set(bank_name)

        self._root.configure(bg=bg)
        self._frame.configure(bg=bg)
        self._bank_label.configure(
            bg=bg, fg=fg,
            font=(FONT_BANK[0], font_size, FONT_BANK[2]),
        )
        self._bankset_label.configure(bg=bg)

        if "width" in style or "height" in style:
            w = style.get("width",  self._root.winfo_width())
            h = style.get("height", self._root.winfo_height())
            self._root.geometry(f"{w}x{h}")

    def _on_close(self):
        """Handle the window close button (titled mode only)."""
        self._running = False
        self._root.destroy()
