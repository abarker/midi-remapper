"""
test_bankset_realclock.py

BankSet timers on the real scheduler thread and the real clock, with no
FakeTimer.  test_bankset.py covers the gesture logic; these check that
its timers reach the scheduler, fire there on time, and stop when they
should.  Tolerances are loose so a loaded machine doesn't fail them.
"""
import threading
import time

from conftest import make_bankset, make_pc, make_cc
from midi_event_remapper.scheduler import get_scheduler


def wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.001)
    return False


def recorder(bs):
    """Route bs's timer output to a list of (time, thread name, event)."""
    got = []

    def output_fn(ev):
        got.append((time.monotonic(), threading.current_thread().name, ev))

    bs.set_output_fn(output_fn)
    return got


def test_delayed_send_fires_on_the_scheduler_thread():
    bs, _ = make_bankset({"default": {
        "PC5": [{"send": "CC10", "value": 1, "delay": 0.05}],
    }})
    got = recorder(bs)
    t0 = time.monotonic()
    assert bs.handle(make_pc(5)) == []
    assert wait_until(lambda: got)
    when, thread_name, ev = got[0]
    assert 0.045 <= when - t0 < 0.5
    assert thread_name == get_scheduler()._thread.name
    assert ev.ctrl == 10


def test_long_press_fires_while_held():
    bs, _ = make_bankset({"default": {
        "CC30": {
            "single": [{"send": "PC1"}],
            "long":   [{"send": "PC2"}],
        },
    }}, long_press_ms=60)
    got = recorder(bs)
    t0 = time.monotonic()
    bs.handle(make_cc(30, value=127))
    assert wait_until(lambda: got)
    assert 0.055 <= got[0][0] - t0 < 0.5
    assert got[0][2].program == 2
    bs.handle(make_cc(30, value=0))
    time.sleep(0.05)
    assert len(got) == 1


def test_double_press_fires_once_after_the_window():
    bs, _ = make_bankset({"default": {
        "PC4": {
            "single": [{"send": "CC10", "value": 1}],
            "double": [{"send": "CC11", "value": 2}],
        },
    }}, multi_press_window_ms=80)
    got = recorder(bs)
    bs.handle(make_pc(4))
    bs.handle(make_pc(4))
    time.sleep(0.3)
    assert [ev.ctrl for _, _, ev in got] == [11]


def test_repeat_runs_while_held_and_stops_at_release():
    bs, _ = make_bankset({"default": {
        "CC0": {
            "repeat": [{"send": "CC10", "value": 127}],
            "repeat_delay_ms": 50,
            "repeat_ms":       20,
        },
    }})
    got = recorder(bs)
    bs.handle(make_cc(0, value=127))
    time.sleep(0.25)
    bs.handle(make_cc(0, value=0))
    n = len(got)
    assert n >= 4                      # about 10 at these settings
    time.sleep(0.15)
    assert len(got) == n               # nothing after the release


def test_no_thread_per_timer():
    get_scheduler()                    # started before the baseline
    bs, _ = make_bankset({"default": {
        "PC5": [{"send": "CC10", "value": 1, "delay": 0.02}],
    }})
    counts = []

    def output_fn(ev):
        counts.append(threading.active_count())

    bs.set_output_fn(output_fn)
    baseline = threading.active_count()
    for _ in range(50):
        bs.handle(make_pc(5))
        counts.append(threading.active_count())
    assert wait_until(lambda: len(counts) == 100)
    assert max(counts) <= baseline


def test_cancel_timers_stops_pending_ones():
    bs, _ = make_bankset({"default": {
        "PC5": [{"send": "CC10", "value": 1, "delay": 0.1}],
    }})
    got = recorder(bs)
    bs.handle(make_pc(5))
    bs.cancel_timers()                 # as on a config reload
    time.sleep(0.25)
    assert got == []


def test_failing_send_does_not_stop_later_timers(capsys):
    bs, _ = make_bankset({"default": {
        "PC5": [{"send": "CC10", "value": 1, "delay": 0.02}],
        "PC6": [{"send": "CC11", "value": 1, "delay": 0.05}],
    }})
    got = []

    def output_fn(ev):
        if ev.ctrl == 10:
            raise RuntimeError("output failed")
        got.append(ev)

    bs.set_output_fn(output_fn)
    bs.handle(make_pc(5))
    bs.handle(make_pc(6))
    assert wait_until(lambda: got)
    assert got[0].ctrl == 11
