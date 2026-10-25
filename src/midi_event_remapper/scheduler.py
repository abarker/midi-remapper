"""scheduler.py

One scheduler thread for timed callbacks, in place of a thread per timer.

Not used yet: ``BankSet`` still starts a ``threading.Timer`` for every
deferred action (see ``BankSet._start_timer``).  Under ``--jack-rt`` each
of those starts creates an OS thread inside the JACK callback.  With this
module, starting a timer only puts it on a queue, which never blocks and
creates no thread; one long-lived thread waits for the earliest deadline
and runs the callbacks one at a time.  See ROADMAP entry 5.

``Timer`` offers the subset of ``threading.Timer`` that ``BankSet`` uses
(the constructor, ``daemon``, ``start()``, ``cancel()``, ``is_alive()``),
so switching over is a change to ``BankSet._start_timer`` only, and the
tests' ``FakeTimer`` keeps standing in for both.

Cancellation is lazy: ``cancel()`` marks the timer, and the scheduler
drops it when its deadline comes up.  As with ``threading.Timer``, a
cancel only works while the timer is still waiting; once its callback
has started, it runs to the end.
"""
import heapq
import itertools
import os
import queue
import sys
import threading
import time
import traceback

# Timer states.
_NEW       = "new"
_PENDING   = "pending"
_RUNNING   = "running"
_DONE      = "done"
_CANCELED  = "canceled"

_STOP = object()   # inbox sentinel: stop the scheduler thread


class Timer:
    """A timed callback run by a ``Scheduler``; see ``threading.Timer``.

    Parameters
    ----------
    interval : float
        Seconds from ``start()`` to the call.
    function : callable
        Called as ``function(*args, **kwargs)`` on the scheduler thread.
    args, kwargs
        As for ``threading.Timer``.
    scheduler : Scheduler or None
        The scheduler to run on; None means the shared one from
        ``get_scheduler()``.
    """

    __slots__ = ("interval", "function", "args", "kwargs", "daemon",
                 "_scheduler", "_state", "_due")

    def __init__(self, interval, function, args=None, kwargs=None,
                 scheduler=None):
        self.interval   = interval
        self.function   = function
        self.args       = args if args is not None else ()
        self.kwargs     = kwargs if kwargs is not None else {}
        self.daemon     = True    # accepted for compatibility; no effect
        self._scheduler = scheduler
        self._state     = _NEW
        self._due       = None

    def start(self):
        """Queue the timer.  Never blocks; safe in the JACK callback."""
        if self._state is _CANCELED and self._due is None:
            self._due = time.monotonic()  # canceled before start: never runs
            return
        if self._state is not _NEW:
            raise RuntimeError("timer can only be started once")
        sched = self._scheduler or get_scheduler()
        self._due   = time.monotonic() + self.interval
        self._state = _PENDING
        sched._submit(self)

    def cancel(self):
        """Stop the timer if it is still waiting."""
        if self._state is _PENDING or self._state is _NEW:
            self._state = _CANCELED

    def is_alive(self):
        """True from ``start()`` until the callback returns or the timer is
        canceled, like a ``threading.Timer``'s thread."""
        return self._state is _PENDING or self._state is _RUNNING


class Scheduler:
    """Runs ``Timer`` callbacks at their deadlines on one thread.

    Parameters
    ----------
    name : str
        Thread name.
    priority : int or None
        If given, the thread asks for ``SCHED_FIFO`` at this priority.
        Failure (no permission, unsupported platform) is recorded in
        ``priority_error`` and the thread runs at normal priority.
    on_error : callable or None
        Called as ``on_error(timer, exc)`` when a callback raises.  The
        default prints the traceback to stderr.  Either way the scheduler
        carries on with the next timer.
    """

    def __init__(self, name="TimerScheduler", priority=None, on_error=None):
        self._name           = name
        self._priority       = priority
        self._on_error       = on_error or _print_error
        self._inbox          = queue.SimpleQueue()
        self._heap           = []              # (due, seq, timer)
        self._seq            = itertools.count()
        self._thread         = None
        self._stopped        = False
        self.priority_error  = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self):
        """Start the scheduler thread."""
        self._thread = threading.Thread(
            target = self._run,
            name   = self._name,
            daemon = True,
        )
        self._thread.start()

    def stop(self, timeout=1.0):
        """Stop the thread.  Timers still waiting never fire."""
        self._stopped = True
        self._inbox.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _submit(self, timer):
        if self._stopped:
            raise RuntimeError("scheduler is stopped")
        self._inbox.put(timer)

    def _set_priority(self):
        try:
            # pid 0 is the calling thread on Linux.
            os.sched_setscheduler(0, os.SCHED_FIFO,
                                  os.sched_param(self._priority))
        except (AttributeError, OSError) as exc:
            self.priority_error = exc

    def _run(self):
        """Wait for new timers or the earliest deadline, whichever comes
        first, and run whatever is due (scheduler thread)."""
        if self._priority is not None:
            self._set_priority()
        heap = self._heap
        while True:
            if heap:
                timeout = max(0.0, heap[0][0] - time.monotonic())
            else:
                timeout = None
            try:
                item = self._inbox.get(timeout=timeout)
            except queue.Empty:
                item = None
            # Take everything queued so far before running anything.
            while item is not None:
                if item is _STOP:
                    return
                heapq.heappush(heap, (item._due, next(self._seq), item))
                try:
                    item = self._inbox.get_nowait()
                except queue.Empty:
                    item = None

            now = time.monotonic()
            while heap and heap[0][0] <= now:
                _due, _seq, timer = heapq.heappop(heap)
                if timer._state is not _PENDING:
                    continue            # canceled while waiting
                timer._state = _RUNNING
                try:
                    timer.function(*timer.args, **timer.kwargs)
                except Exception as exc:
                    try:
                        self._on_error(timer, exc)
                    except Exception:
                        pass
                finally:
                    timer._state = _DONE
                if self._stopped:
                    return
                now = time.monotonic()


def _print_error(timer, exc):
    print(f"[scheduler] exception in timer callback "
          f"{getattr(timer.function, '__qualname__', timer.function)!r}:",
          file=sys.stderr)
    traceback.print_exception(type(exc), exc, exc.__traceback__,
                              file=sys.stderr)


# ----------------------------------------------------------------------
# Shared scheduler
# ----------------------------------------------------------------------

_shared      = None
_shared_lock = threading.Lock()


def get_scheduler():
    """Return the shared scheduler, starting it on first use."""
    global _shared
    if _shared is None:
        with _shared_lock:
            if _shared is None:
                sched = Scheduler()
                sched.start()
                _shared = sched
    return _shared
