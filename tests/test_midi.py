"""
test_midi.py

Tests for the three hot-path functions in midi.py / midi_core.pyx:
event_key(), is_release(), and build_event().

The TestImplementationPath class verifies *which* implementation is
active.  When the Cython extension has been built and installed, these
tests confirm it is actually executing -- not silently falling back to
the pure Python code.  If the extension has not been built, the same
functional tests run against the pure Python fallback and the
implementation-path tests report that cleanly.
"""
import sys
import pytest

from conftest import make_cc, make_note, make_noteoff, make_pc
from midi_event_remapper.midi import (
    _CYTHON_CORE, event_key, is_release, build_event,
)
from midi_event_remapper.mock_mididings import (
    FakeInputEvent, CTRL, NOTEON, NOTEOFF, PROGRAM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctrl_event(ctrl, value=127):
    return make_cc(ctrl=ctrl, value=value)

def _note_event(note, velocity=127):
    return make_note(note=note, velocity=velocity)

def _noteoff_event(note):
    return make_noteoff(note=note)

def _pc_event(program):
    return make_pc(program=program)


# ---------------------------------------------------------------------------
# event_key
# ---------------------------------------------------------------------------

class TestEventKey:

    def test_ctrl(self):
        """CC event produces 'CC<n>' key."""
        assert event_key(_ctrl_event(0))  == "CC0"
        assert event_key(_ctrl_event(5))  == "CC5"
        assert event_key(_ctrl_event(127)) == "CC127"

    def test_ctrl_release(self):
        """CC=0 (release signal) still maps to a CC key, not None."""
        assert event_key(_ctrl_event(5, value=0)) == "CC5"

    def test_noteon(self):
        """NoteOn event produces 'NOTE<n>' key."""
        assert event_key(_note_event(0))   == "NOTE0"
        assert event_key(_note_event(60))  == "NOTE60"
        assert event_key(_note_event(127)) == "NOTE127"

    def test_noteoff(self):
        """NoteOff maps to the same 'NOTE<n>' key as NoteOn."""
        assert event_key(_noteoff_event(60)) == "NOTE60"

    def test_program(self):
        """Program-change event produces 'PC<n>' key."""
        assert event_key(_pc_event(0))   == "PC0"
        assert event_key(_pc_event(1))   == "PC1"
        assert event_key(_pc_event(127)) == "PC127"

    def test_unknown_type_returns_none(self):
        """An unrecognised event type returns None."""
        ev = FakeInputEvent(0, port=1, channel=1)   # 0 is not CTRL/NOTEON/etc.
        assert event_key(ev) is None


# ---------------------------------------------------------------------------
# is_release
# ---------------------------------------------------------------------------

class TestIsRelease:

    def test_cc_zero_is_release(self):
        assert is_release(_ctrl_event(5, value=0)) is True

    def test_cc_nonzero_is_not_release(self):
        assert is_release(_ctrl_event(5, value=127)) is False
        assert is_release(_ctrl_event(5, value=1))   is False

    def test_noteoff_is_release(self):
        assert is_release(_noteoff_event(60)) is True

    def test_noteon_is_not_release(self):
        assert is_release(_note_event(60)) is False

    def test_pc_is_not_release(self):
        assert is_release(_pc_event(1)) is False


# ---------------------------------------------------------------------------
# build_event
# ---------------------------------------------------------------------------

class TestBuildEvent:

    def test_cc_fixed_value(self):
        item = {"send": "CC10", "value": 64}
        ev = build_event(item, port=1, channel=5)
        assert ev.kind  == "CC"
        assert ev.ctrl  == 10
        assert ev.value == 64

    def test_cc_passthrough_value(self):
        """When 'value' absent, event_value is forwarded."""
        item = {"send": "CC10"}
        ev = build_event(item, port=1, channel=5, event_value=42)
        assert ev.value == 42

    def test_cc_default_value(self):
        """When 'value' absent and no event_value, defaults to 127."""
        item = {"send": "CC10"}
        ev = build_event(item, port=1, channel=5)
        assert ev.value == 127

    def test_pc(self):
        item = {"send": "PC7"}
        ev = build_event(item, port=1, channel=5)
        assert ev.kind    == "PC"
        assert ev.program == 7

    def test_note_on(self):
        item = {"send": "NOTE60", "velocity": 100}
        ev = build_event(item, port=1, channel=5)
        assert ev.kind     == "NOTEON"
        assert ev.note     == 60
        assert ev.velocity == 100

    def test_note_off(self):
        item = {"send": "NOTE60", "note_off": True}
        ev = build_event(item, port=1, channel=5)
        assert ev.kind == "NOTEOFF"
        assert ev.note == 60

    def test_note_default_velocity(self):
        item = {"send": "NOTE60"}
        ev = build_event(item, port=1, channel=5)
        assert ev.velocity == 127

    def test_unhandled_send_raises(self):
        item = {"send": "XY99"}
        with pytest.raises(ValueError, match="unhandled send"):
            build_event(item, port=1, channel=5)


# ---------------------------------------------------------------------------
# Implementation-path verification
# ---------------------------------------------------------------------------

class TestImplementationPath:
    """Assert which implementation is active and that it is consistent.

    These tests catch the case where the Cython extension is built and
    installed but silently failed to be imported (leaving _CYTHON_CORE
    False when it should be True).  They also confirm the correct module
    is backing each function when the extension is active.
    """

    def _extension_importable(self):
        """Return True if midi_core can be imported in this process."""
        try:
            import importlib
            importlib.import_module("midi_event_remapper.midi_core")
            return True
        except ImportError:
            return False

    def test_cython_active_iff_extension_importable(self):
        """_CYTHON_CORE must be True exactly when the .so can be imported."""
        available = self._extension_importable()
        if available:
            assert _CYTHON_CORE, (
                "Cython extension is importable but _CYTHON_CORE is False. "
                "The extension may have raised an error during initialisation."
            )
        else:
            assert not _CYTHON_CORE, (
                "_CYTHON_CORE is True but the extension cannot be imported. "
                "Stale sys.modules entry?"
            )

    def test_event_key_module(self):
        """event_key must come from the correct module for the active path."""
        expected = (
            "midi_event_remapper.midi_core"
            if _CYTHON_CORE else
            "midi_event_remapper.midi"
        )
        assert event_key.__module__ == expected, (
            f"event_key is from {event_key.__module__!r}, "
            f"expected {expected!r}"
        )

    def test_is_release_module(self):
        """is_release must come from the correct module for the active path."""
        expected = (
            "midi_event_remapper.midi_core"
            if _CYTHON_CORE else
            "midi_event_remapper.midi"
        )
        assert is_release.__module__ == expected

    def test_build_event_module(self):
        """build_event must come from the correct module for the active path."""
        expected = (
            "midi_event_remapper.midi_core"
            if _CYTHON_CORE else
            "midi_event_remapper.midi"
        )
        assert build_event.__module__ == expected

    def test_report_active_implementation(self, capsys):
        """Print which implementation is under test (visible with -v or -s)."""
        impl = "Cython (midi_core.so)" if _CYTHON_CORE else "pure Python (midi.py)"
        print(f"\n[midi impl] {impl}", file=sys.stderr)
        # This test always passes; its purpose is to make the path visible.
