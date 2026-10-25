"""Tests for scheduler.py (real threads, real clock).

The scheduler is not used by BankSet yet; these check it on its own.
Timing tolerances are loose so a loaded machine doesn't fail them.
"""
import threading
import time

import pytest

from midi_event_remapper.scheduler import Scheduler, Timer, get_scheduler


@pytest.fixture
def sched():
    s = Scheduler()
    s.start()
    yield s
    s.stop()


def wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.001)
    return False


def test_fires_once_after_interval(sched):
    calls = []
    t0 = time.monotonic()
    Timer(0.05, lambda: calls.append(time.monotonic() - t0),
          scheduler=sched).start()
    assert wait_until(lambda: calls)
    time.sleep(0.05)
    assert len(calls) == 1
    assert 0.05 <= calls[0] < 0.1


def test_args_and_kwargs_passed(sched):
    got = []
    Timer(0.0, lambda *a, **k: got.append((a, k)), args=(1, 2),
          kwargs={"x": 3}, scheduler=sched).start()
    assert wait_until(lambda: got)
    assert got == [((1, 2), {"x": 3})]


def test_fires_in_deadline_order(sched):
    order = []
    for name, delay in (("c", 0.06), ("a", 0.02), ("b", 0.04)):
        Timer(delay, order.append, args=(name,), scheduler=sched).start()
    assert wait_until(lambda: len(order) == 3)
    assert order == ["a", "b", "c"]


def test_equal_deadlines_fire_in_start_order(sched):
    order = []
    gate = threading.Event()
    # Hold the scheduler busy so all of them are queued before any is due.
    Timer(0.0, gate.wait, args=(1.0,), scheduler=sched).start()
    timers = [Timer(0.0, order.append, args=(i,), scheduler=sched)
              for i in range(20)]
    for t in timers:
        t.start()
    gate.set()
    assert wait_until(lambda: len(order) == 20)
    assert order == list(range(20))


def test_cancel_before_due_prevents_call(sched):
    calls = []
    t = Timer(0.05, calls.append, args=(1,), scheduler=sched)
    t.start()
    assert t.is_alive()
    t.cancel()
    assert not t.is_alive()
    time.sleep(0.1)
    assert calls == []


def test_cancel_before_start(sched):
    calls = []
    t = Timer(0.0, calls.append, args=(1,), scheduler=sched)
    t.cancel()
    t.start()                        # allowed, as with threading.Timer
    time.sleep(0.02)
    assert calls == []
    assert not t.is_alive()
    with pytest.raises(RuntimeError):
        t.start()


def test_cancel_after_run_is_harmless(sched):
    calls = []
    t = Timer(0.0, calls.append, args=(1,), scheduler=sched)
    t.start()
    assert wait_until(lambda: calls)
    t.cancel()
    assert calls == [1]
    assert not t.is_alive()


def test_is_alive_through_the_callback(sched):
    inside = threading.Event()
    release = threading.Event()

    def slow():
        inside.set()
        release.wait(1.0)

    t = Timer(0.0, slow, scheduler=sched)
    assert not t.is_alive()          # not started
    t.start()
    assert inside.wait(1.0)
    assert t.is_alive()              # running
    release.set()
    assert wait_until(lambda: not t.is_alive())


def test_start_twice_raises(sched):
    t = Timer(10.0, lambda: None, scheduler=sched)
    t.start()
    with pytest.raises(RuntimeError):
        t.start()
    t.cancel()


def test_exception_does_not_stop_later_timers():
    errors = []
    s = Scheduler(on_error=lambda timer, exc: errors.append(exc))
    s.start()
    try:
        calls = []

        def boom():
            raise ValueError("boom")

        Timer(0.0, boom, scheduler=s).start()
        Timer(0.02, calls.append, args=(1,), scheduler=s).start()
        assert wait_until(lambda: calls)
        assert len(errors) == 1 and isinstance(errors[0], ValueError)
        assert s.is_running()
    finally:
        s.stop()


def test_default_error_handler_prints(capsys):
    s = Scheduler()
    s.start()
    try:
        done = []

        def boom():
            raise ValueError("boom")

        Timer(0.0, boom, scheduler=s).start()
        Timer(0.01, done.append, args=(1,), scheduler=s).start()
        assert wait_until(lambda: done)
    finally:
        s.stop()
    err = capsys.readouterr().err
    assert "boom" in err and "ValueError" in err


def test_callback_can_reschedule_itself(sched):
    """The repeat pattern: each firing starts the next timer."""
    times = []

    def tick():
        times.append(time.monotonic())
        if len(times) < 5:
            Timer(0.01, tick, scheduler=sched).start()

    Timer(0.01, tick, scheduler=sched).start()
    assert wait_until(lambda: len(times) == 5)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.009 for g in gaps)


def test_callback_can_cancel_a_later_timer(sched):
    calls = []
    later = Timer(0.05, calls.append, args=("later",), scheduler=sched)
    later.start()
    Timer(0.01, later.cancel, scheduler=sched).start()
    time.sleep(0.1)
    assert calls == []


def test_new_earlier_timer_wakes_the_scheduler(sched):
    """A timer due sooner than the one being waited on fires on time."""
    calls = []
    Timer(1.0, calls.append, args=("slow",), scheduler=sched).start()
    time.sleep(0.02)                  # scheduler now waiting on 1.0 s
    t0 = time.monotonic()
    Timer(0.02, lambda: calls.append(time.monotonic() - t0),
          scheduler=sched).start()
    assert wait_until(lambda: calls)
    assert calls[0] < 0.1


def test_many_timers_all_fire(sched):
    count = [0]
    lock = threading.Lock()

    def inc():
        with lock:
            count[0] += 1

    for i in range(1000):
        Timer((i % 50) / 1000.0, inc, scheduler=sched).start()
    assert wait_until(lambda: count[0] == 1000, timeout=3.0)


def test_lateness_is_small(sched):
    """Median lateness well under a JACK period (5.3 ms on the rig)."""
    late = []

    def make(due):
        return lambda: late.append(time.monotonic() - due)

    for i in range(50):
        delay = 0.005 + i * 0.003
        Timer(delay, make(time.monotonic() + delay), scheduler=sched).start()
    assert wait_until(lambda: len(late) == 50)
    late.sort()
    assert late[0] >= 0
    assert late[25] < 0.002


def test_stop_drops_waiting_timers():
    s = Scheduler()
    s.start()
    calls = []
    Timer(0.05, calls.append, args=(1,), scheduler=s).start()
    s.stop()
    assert not s.is_running()
    time.sleep(0.1)
    assert calls == []
    with pytest.raises(RuntimeError):
        Timer(0.0, calls.append, args=(2,), scheduler=s).start()


def test_priority_request_never_breaks_it():
    """SCHED_FIFO may be refused (no rtprio limit); timers run either way."""
    s = Scheduler(priority=10)
    s.start()
    try:
        calls = []
        Timer(0.0, calls.append, args=(1,), scheduler=s).start()
        assert wait_until(lambda: calls)
        assert s.priority_error is None or isinstance(s.priority_error,
                                                      OSError)
    finally:
        s.stop()


def test_shared_scheduler_is_started_once():
    a = get_scheduler()
    b = get_scheduler()
    assert a is b and a.is_running()
    calls = []
    Timer(0.0, calls.append, args=(1,)).start()
    assert wait_until(lambda: calls)
