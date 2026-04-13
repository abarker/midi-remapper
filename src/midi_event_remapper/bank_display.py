"""
bank_display.py

A small tkinter window that always shows the current active bank name
across all BankSets.  Intended for use during live performance so the
player can glance at it to confirm which bank is active.

The window runs in its own thread and is updated via a thread-safe queue.
It stays on top of other windows so it remains visible while playing.

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
import queue
import threading
import tkinter as tk


# Colour pairs (background, foreground) keyed by bank name.
# Banks not in this dict get the default colour.
# Extend or replace in your config if desired.
BANK_COLOURS = {
    "default":     ("#1a1a2e", "#e0e0ff"),
    "drums":       ("#1a2e1a", "#a0ffb0"),
    "ardour":      ("#2e1a1a", "#ffb0a0"),
    "sooperlooper":("#1a2a2e", "#a0e8ff"),
}

DEFAULT_BG = "#1a1a1a"
DEFAULT_FG = "#ffffff"

FONT_BANKSET = ("Helvetica", 14)
FONT_BANK    = ("Helvetica", 72, "bold")
WINDOW_TITLE = "Bank Display"
POLL_MS      = 50   # how often the Tk event loop checks the queue (ms)


class BankDisplay:
    """
    Thread-safe bank name display window.

    The tkinter mainloop runs in a dedicated daemon thread so it does not
    block the mididings event loop.  Bank updates are sent via a queue and
    processed by the Tk thread on its next poll cycle.
    """

    def __init__(self):
        self._queue   = queue.Queue()
        self._thread  = None
        self._root    = None
        self._running = False

        # Tk StringVars -- created in the Tk thread, stored here for access.
        self._bankset_var = None
        self._bank_var    = None
        self._frame       = None

    def start(self):
        """Start the display window in a background thread."""
        self._running = True
        self._thread  = threading.Thread(
            target  = self._run_tk,
            name    = "BankDisplay",
            daemon  = True,
        )
        self._thread.start()

    def stop(self):
        """Close the window and stop the background thread."""
        self._running = False
        self._queue.put(None)  # sentinel to unblock _poll

    def update(self, bankset_name, bank_name):
        """
        Notify the display of a bank change.  Safe to call from any thread.

        Parameters
        ----------
        bankset_name : str
            The name of the BankSet that changed.
        bank_name : str
            The new active bank name.
        """
        self._queue.put((bankset_name, bank_name))

    # ------------------------------------------------------------------
    # Tk thread
    # ------------------------------------------------------------------

    def _run_tk(self):
        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._root.configure(bg=DEFAULT_BG)
        self._root.attributes("-topmost", True)
        self._root.resizable(True, True)

        self._bankset_var = tk.StringVar(value="")
        self._bank_var    = tk.StringVar(value="---")

        # BankSet name in small text at top
        bankset_label = tk.Label(
            self._root,
            textvariable = self._bankset_var,
            font         = FONT_BANKSET,
            bg           = DEFAULT_BG,
            fg           = "#888888",
            pady         = 4,
        )
        bankset_label.pack(fill=tk.X)

        # Bank name in large text
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

        # Handle window close button
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._root.after(POLL_MS, self._poll)
        self._root.mainloop()

    def _poll(self):
        """Process pending queue items and reschedule.

        Also checks whether the main thread is still alive -- if it has
        exited (program finished or crashed), the window closes itself.
        """
        import threading
        main = threading.main_thread()
        if not main.is_alive():
            self._root.destroy()
            return

        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    self._root.destroy()
                    return
                bankset_name, bank_name = item
                self._apply_update(bankset_name, bank_name)
        except queue.Empty:
            pass
        if self._running:
            self._root.after(POLL_MS, self._poll)

    def _apply_update(self, bankset_name, bank_name):
        """Apply a bank change to the Tk widgets."""
        self._bankset_var.set(bankset_name)
        self._bank_var.set(bank_name)

        bg, fg = BANK_COLOURS.get(bank_name, (DEFAULT_BG, DEFAULT_FG))
        self._root.configure(bg=bg)
        self._frame.configure(bg=bg)
        self._bank_label.configure(bg=bg, fg=fg)
        self._bankset_label.configure(bg=bg)

    def _on_close(self):
        """Handle window close -- stop the whole display cleanly."""
        self._running = False
        self._root.destroy()
