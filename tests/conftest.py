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

# If MIDI_REMAPPER_NO_CYTHON is set, block the Cython extension so that
# tests run against the pure Python fallback even when the .so is present.
import os as _os
if _os.environ.get("MIDI_REMAPPER_NO_CYTHON"):
    sys.modules.setdefault("midi_event_remapper.midi_core", None)


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
        self.canceled = False
        FakeTimer.instances.append(self)

    def start(self):
        pass  # no-op: tests fire manually

    def cancel(self):
        self.canceled = True

    def fire(self):
        if not self.canceled:
            self.fn(*self.args)
            self._fired = True

    def is_alive(self):
        return not self.canceled and not getattr(self, '_fired', False)

    @classmethod
    def clear(cls):
        cls.instances.clear()

    @classmethod
    def active(cls):
        """Return all timers that have not been canceled."""
        return [t for t in cls.instances if not t.canceled]


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
# Fixtures wrapping helpers from midi_event_remapper.testing
# ---------------------------------------------------------------------------

from midi_event_remapper.testing import make_bankset, make_pc, make_cc, make_note, make_noteoff


@pytest.fixture
def events():
    """Factory functions for common input event types."""
    return {"pc": make_pc, "cc": make_cc, "note": make_note,
            "noteoff": make_noteoff}


@pytest.fixture
def bankset_factory():
    """Fixture that exposes make_bankset for use in tests."""
    return make_bankset
