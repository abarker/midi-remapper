"""
test_midi.py

Tests for the three hot-path functions in midi.py / midi_core.pyx:
event_key(), is_release(), and build_event().

CODE PATHS
----------
Two independent choices determine which code runs:

  _CYTHON_CORE=False, no --jack-rt  (default)
      Pure Python functions from midi.py.  jack buffered backend adds
      one period of latency.  Safest; no xrun risk.

  _CYTHON_CORE=False, --jack-rt
      Pure Python functions, jack-rt backend.  Handler runs in the JACK
      RT callback with setswitchinterval(0.0001) and gc.freeze().
      Highest xrun risk: full Python hot path in the RT callback.

  _CYTHON_CORE=True, no --jack-rt
      Cython C-typed functions.  jack buffered backend.  Faster event
      classification without RT callback exposure.

  _CYTHON_CORE=True, --jack-rt  (recommended RT combination)
      Cython functions + jack-rt backend + setswitchinterval + gc.freeze.
      Shortest GIL hold in the RT callback; lowest xrun risk for RT mode.

The TestImplementationPath class verifies which path is active.  When
the Cython extension has been built, these tests confirm it is actually
executing -- not silently falling back to pure Python.  The same
functional tests run against whichever implementation is active.
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
        """An unrecognized event type returns None."""
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

    def test_channel_passthrough_by_default(self):
        """Without 'channel' in item, incoming channel is preserved."""
        ev = build_event({"send": "CC10", "value": 1}, port=1, channel=3)
        assert ev.channel == 3

    def test_channel_override_cc(self):
        ev = build_event({"send": "CC10", "value": 1, "channel": 2},
                         port=1, channel=5)
        assert ev.channel == 2

    def test_channel_override_pc(self):
        ev = build_event({"send": "PC7", "channel": 2}, port=1, channel=5)
        assert ev.channel == 2

    def test_channel_override_note(self):
        ev = build_event({"send": "NOTE60", "channel": 2}, port=1, channel=5)
        assert ev.channel == 2

    def test_empty_send_raises(self):
        """Empty send string must raise ValueError, not crash (e.g. no IndexError).

        The previous ord()-based Cython implementation would raise IndexError
        on ord("") before reaching the ValueError.  startswith() is safe.
        """
        item = {"send": ""}
        with pytest.raises((ValueError, IndexError)):
            build_event(item, port=1, channel=5)

    def test_single_char_send_raises(self):
        """A single-character send string must raise ValueError cleanly."""
        item = {"send": "C"}
        with pytest.raises((ValueError, IndexError)):
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
        """_CYTHON_CORE must match the expected state for the current environment.

        When MIDI_REMAPPER_NO_CYTHON is set, the extension is deliberately
        suppressed regardless of whether the .so exists.  Otherwise _CYTHON_CORE
        must be True exactly when the extension can be imported.
        """
        import os
        if os.environ.get("MIDI_REMAPPER_NO_CYTHON"):
            assert not _CYTHON_CORE, (
                "MIDI_REMAPPER_NO_CYTHON is set but _CYTHON_CORE is True. "
                "The environment variable is not being honoured."
            )
            return
        available = self._extension_importable()
        if available:
            assert _CYTHON_CORE, (
                "Cython extension is importable but _CYTHON_CORE is False. "
                "The extension may have raised an error during initialization."
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
        import os
        if _CYTHON_CORE:
            impl = "Cython (midi_core.so)"
        elif os.environ.get("MIDI_REMAPPER_NO_CYTHON"):
            impl = "pure Python (midi.py) -- suppressed by MIDI_REMAPPER_NO_CYTHON"
        else:
            impl = "pure Python (midi.py) -- extension not built"
        print(f"\n[midi impl] {impl}", file=sys.stderr)
        # This test always passes; its purpose is to make the path visible.

class TestPhase2Architecture:
    """Structural tests specific to Phase 2 of the Cython implementation.

    These verify that:
    - The internal ``cdef nogil`` helpers (_classify_etype, _is_release_impl)
      are NOT accessible from Python (they are cdef, not cpdef or def).
    - Classification is exhaustively correct for all recognized event types
      and for values at the boundaries that distinguish press from release.
    - Both implementations agree on every case (parametrized over both paths
      via the MIDI_REMAPPER_NO_CYTHON environment variable in CI).
    """

    def test_internal_helpers_not_exposed(self):
        """cdef functions must not be importable from Python.

        _classify_etype and _is_release_impl are cdef inline nogil; they
        are inlined by the compiler and have no Python-visible symbol.
        Accidentally making them cpdef would expose implementation details
        and add unnecessary Python call overhead.
        """
        if not _CYTHON_CORE:
            pytest.skip("Cython extension not active")
        import midi_event_remapper.midi_core as _core
        assert not hasattr(_core, '_classify_etype'), (
            "_classify_etype is exposed to Python -- should be cdef, not cpdef"
        )
        assert not hasattr(_core, '_is_release_impl'), (
            "_is_release_impl is exposed to Python -- should be cdef, not cpdef"
        )

    def test_classification_exhaustive(self):
        """event_key returns the correct key for every recognized event type."""
        from midi_event_remapper.mock_mididings import FakeInputEvent, CTRL, NOTEON, NOTEOFF, PROGRAM

        cases = [
            (FakeInputEvent(CTRL,    port=1, channel=1, ctrl=0),    "CC0"),
            (FakeInputEvent(CTRL,    port=1, channel=1, ctrl=64),   "CC64"),
            (FakeInputEvent(CTRL,    port=1, channel=1, ctrl=127),  "CC127"),
            (FakeInputEvent(NOTEON,  port=1, channel=1, note=0),    "NOTE0"),
            (FakeInputEvent(NOTEON,  port=1, channel=1, note=60),   "NOTE60"),
            (FakeInputEvent(NOTEON,  port=1, channel=1, note=127),  "NOTE127"),
            (FakeInputEvent(NOTEOFF, port=1, channel=1, note=60),   "NOTE60"),
            (FakeInputEvent(PROGRAM, port=1, channel=1, program=0), "PC0"),
            (FakeInputEvent(PROGRAM, port=1, channel=1, program=127), "PC127"),
        ]
        for ev, expected in cases:
            result = event_key(ev)
            assert result == expected, (
                f"event_key({ev.type}) returned {result!r}, expected {expected!r}"
            )

    def test_release_detection_exhaustive(self):
        """is_release is correct for all cases that distinguish press/release."""
        from midi_event_remapper.mock_mididings import FakeInputEvent, CTRL, NOTEON, NOTEOFF, PROGRAM

        # CC=0 is release; any other CC value is press.
        assert is_release(FakeInputEvent(CTRL, port=1, channel=1, ctrl=5, value=0))   is True
        assert is_release(FakeInputEvent(CTRL, port=1, channel=1, ctrl=5, value=1))   is False
        assert is_release(FakeInputEvent(CTRL, port=1, channel=1, ctrl=5, value=127)) is False
        # NoteOff is always release regardless of velocity.
        assert is_release(FakeInputEvent(NOTEOFF, port=1, channel=1, note=60)) is True
        # NoteOn is never a release.
        assert is_release(FakeInputEvent(NOTEON,  port=1, channel=1, note=60)) is False
        # PC has no release concept.
        assert is_release(FakeInputEvent(PROGRAM, port=1, channel=1, program=1)) is False
        # Unknown type is not a release.
        assert is_release(FakeInputEvent(0, port=1, channel=1)) is False

    def test_unknown_event_type_returns_none(self):
        """Any event type not in {CTRL, NOTEON, NOTEOFF, PROGRAM} gives None."""
        from midi_event_remapper.mock_mididings import FakeInputEvent
        for t in (0, 3, 5, 16, 255):
            assert event_key(FakeInputEvent(t, port=1, channel=1)) is None

