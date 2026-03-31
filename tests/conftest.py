"""
conftest.py

Pytest configuration and shared fixtures.

The sys.modules injection at module level runs before any test file
imports, ensuring that when midi.py does 'from mididings import ...'
it receives the mock objects instead of the real mididings library.
"""
import sys
import threading
import pytest

# ---------------------------------------------------------------------------
# Inject mock mididings before any src imports occur.
# ---------------------------------------------------------------------------
from midi_event_remapper.mock_mididings import (
    FakeInputEvent,
    engine as mock_engine,
)
import midi_event_remapper.mock_mididings as _mock

sys.modules.setdefault("mididings",        _mock)
sys.modules.setdefault("mididings.event",  _mock)
sys.modules.setdefault("mididings.engine", _mock.engine)

# ---------------------------------------------------------------------------
# FakeTimer: replaces threading.Timer so tests control when timers fire.
# ---------------------------------------------------------------------------

class FakeTimer:
    """
    Drop-in replacement for threading.Timer that does not start a real
    thread.  Timers accumulate in FakeTimer.instances and must be fired
    manually in tests via timer.fire().
    """
    instances = []

    def __init__(self, delay, fn, args=()):
        self.delay     = delay
        self.fn        = fn
        self.args      = args
        self.cancelled = False
        FakeTimer.instances.append(self)

    def start(self):
        pass  # no-op: tests fire manually

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.fn(*self.args)

    @classmethod
    def clear(cls):
        cls.instances.clear()

    @classmethod
    def active(cls):
        """Return all timers that have not been cancelled."""
        return [t for t in cls.instances if not t.cancelled]


@pytest.fixture
def fake_timer(monkeypatch):
    """
    Patch threading.Timer with FakeTimer for the duration of a test.
    Returns the FakeTimer class so tests can inspect and fire timers.
    """
    FakeTimer.clear()
    monkeypatch.setattr(threading, "Timer", FakeTimer)
    return FakeTimer


# ---------------------------------------------------------------------------
# Event factory
# ---------------------------------------------------------------------------

def make_pc(program, port=1, channel=1):
    return FakeInputEvent("PROGRAM", port=port, channel=channel,
                          program=program)

def make_cc(ctrl, value=127, port=1, channel=1):
    return FakeInputEvent("CTRL", port=port, channel=channel,
                          ctrl=ctrl, value=value)

def make_note(note, port=1, channel=1):
    return FakeInputEvent("NOTEON", port=port, channel=channel, note=note)


@pytest.fixture
def events():
    """Factory functions for common input event types."""
    return {"pc": make_pc, "cc": make_cc, "note": make_note}


# ---------------------------------------------------------------------------
# BankSet factory
# ---------------------------------------------------------------------------

from midi_event_remapper.bankset import BankSet


def make_bankset(banks, active_bank="default", **kwargs):
    """
    Create a BankSet wired to a captured output list.

    Returns (bankset, output_list) where output_list accumulates every
    event passed to output_fn.
    """
    captured = []
    bs = BankSet(
        name                  = "test",
        banks                 = banks,
        active_bank           = active_bank,
        output_fn             = captured.append,
        debug                 = False,
        data_offset           = kwargs.pop("data_offset", 1),
        debounce_ms           = kwargs.pop("debounce_ms", 0),
        multi_press_window_ms = kwargs.pop("multi_press_window_ms", 300),
        chord_window_ms       = kwargs.pop("chord_window_ms", 80),
        long_press_ms         = kwargs.pop("long_press_ms", 500),
        **kwargs,
    )
    return bs, captured


@pytest.fixture
def bankset_factory():
    """Fixture that exposes make_bankset for use in tests."""
    return make_bankset
