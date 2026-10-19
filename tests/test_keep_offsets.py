"""
test_keep_offsets.py

--keep-offsets (experimental): immediate outputs carry the input event's
frame, so mididings sends them at the input's position in the JACK period.
Off by default, and then nothing changes.  enable_keep_offsets() must stay
off, with a reason, whenever the mididings functions it relies on are
missing or don't round-trip a frame.

A fake ``_mididings`` module stands in for the real extension: it encodes
a mock event's fields as bytes and keeps the frame as an attribute.
"""
import pickle
import sys
import types

import pytest

from conftest import make_bankset, make_pc
import midi_event_remapper.midi as midi
import midi_event_remapper.mock_mididings as mock


def _fields(ev):
    """The MIDI content: everything but the frame and the test marker."""
    return {k: v for k, v in sorted(ev.__dict__.items())
            if k not in ("frame", "finalized")}


def _to_buffer(ev):
    return (list(pickle.dumps(_fields(ev))),
            ev.__dict__.get("port", 1), getattr(ev, "frame", 0))


def _from_buffer(data, port, frame):
    fields = pickle.loads(bytes(data))
    ev = mock.FakeOutputEvent(fields.pop("kind"), **fields)
    ev.frame = frame
    return ev


def _fake_module(to_buffer=_to_buffer, from_buffer=_from_buffer):
    mod = types.ModuleType("_mididings")
    if to_buffer is not None:
        mod.midi_event_to_buffer = to_buffer
    if from_buffer is not None:
        mod.buffer_to_midi_event = from_buffer
    return mod


@pytest.fixture(autouse=True)
def restore_switch(monkeypatch):
    """Every test starts with --keep-offsets off and leaves it off."""
    monkeypatch.setattr(midi, "KEEP_OFFSETS", False)
    monkeypatch.setattr(midi, "_to_buffer", None)
    monkeypatch.setattr(midi, "_from_buffer", None)


class FakeMidiEvent(mock.FakeOutputEvent):
    """Stands in for mididings.event.MidiEvent: Process() calls
    _finalize() on every returned event."""
    def _finalize(self):
        self.finalized = True


@pytest.fixture
def fake_mididings(monkeypatch):
    monkeypatch.setitem(sys.modules, "_mididings", _fake_module())
    monkeypatch.setattr(mock, "MidiEvent", FakeMidiEvent, raising=False)


def _pc_with_frame(program, frame):
    ev = make_pc(program)
    ev.frame = frame
    return ev


# ---------------------------------------------------------------------------
# enable_keep_offsets()
# ---------------------------------------------------------------------------

class TestEnable:

    def test_enables_with_working_functions(self, fake_mididings):
        assert midi.enable_keep_offsets("jack-rt") is None
        assert midi.KEEP_OFFSETS

    def test_buffered_jack_backend_allowed(self, fake_mididings):
        assert midi.enable_keep_offsets("jack") is None

    def test_off_for_alsa_backend(self, fake_mididings):
        reason = midi.enable_keep_offsets("alsa")
        assert "JACK" in reason
        assert not midi.KEEP_OFFSETS

    def test_off_without_module(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "_mididings", None)  # import fails
        reason = midi.enable_keep_offsets("jack-rt")
        assert "not found" in reason
        assert not midi.KEEP_OFFSETS

    def test_off_when_functions_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "_mididings",
                            _fake_module(from_buffer=None))
        reason = midi.enable_keep_offsets("jack-rt")
        assert "buffer_to_midi_event" in reason
        assert not midi.KEEP_OFFSETS

    def test_off_when_frame_does_not_survive(self, fake_mididings, monkeypatch):
        def drops_frame(data, port, frame):
            return _from_buffer(data, port, 0)
        monkeypatch.setitem(sys.modules, "_mididings",
                            _fake_module(from_buffer=drops_frame))
        reason = midi.enable_keep_offsets("jack-rt")
        assert "self-test failed" in reason
        assert not midi.KEEP_OFFSETS

    def test_off_without_event_class(self, fake_mididings, monkeypatch):
        monkeypatch.delattr(mock, "MidiEvent")
        reason = midi.enable_keep_offsets("jack-rt")
        assert "MidiEvent" in reason
        assert not midi.KEEP_OFFSETS

    def test_off_when_finalize_fails(self, fake_mididings, monkeypatch):
        class NoFinalize(mock.FakeOutputEvent):
            pass
        monkeypatch.setattr(mock, "MidiEvent", NoFinalize)
        reason = midi.enable_keep_offsets("jack-rt")
        assert "self-test failed" in reason
        assert not midi.KEEP_OFFSETS

    def test_off_when_functions_raise(self, fake_mididings, monkeypatch):
        def broken(ev):
            raise TypeError("no")
        monkeypatch.setitem(sys.modules, "_mididings",
                            _fake_module(to_buffer=broken))
        reason = midi.enable_keep_offsets("jack-rt")
        assert "self-test failed" in reason
        assert not midi.KEEP_OFFSETS


# ---------------------------------------------------------------------------
# Effect on remapped events
# ---------------------------------------------------------------------------

BANKS = {"default": {
    "PC5": [{"send": "NOTE36", "velocity": 100},
            {"send": "CC10", "value": 64}],
    "PC6": [{"send": "CC11", "value": 1, "delay": 0.1}],
}}


class TestOutputs:

    def test_off_by_default_outputs_unchanged(self, fake_mididings):
        bs, out = make_bankset(BANKS)
        result = bs.handle(_pc_with_frame(5, 777))
        assert [r.kind for r in result] == ["NOTEON", "CC"]
        assert all(not hasattr(r, "frame") for r in result)

    def test_immediate_outputs_carry_input_frame(self, fake_mididings):
        assert midi.enable_keep_offsets("jack-rt") is None
        bs, out = make_bankset(BANKS)
        result = bs.handle(_pc_with_frame(5, 777))
        assert [r.frame for r in result] == [777, 777]
        assert all(isinstance(r, FakeMidiEvent) for r in result)
        assert result[0].kind == "NOTEON" and result[0].note == 36
        assert result[0].velocity == 100
        assert result[1].kind == "CC" and result[1].ctrl == 10
        assert result[1].value == 64

    def test_delayed_outputs_not_retimed(self, fake_mididings, fake_timer):
        assert midi.enable_keep_offsets("jack-rt") is None
        bs, out = make_bankset(BANKS)
        assert bs.handle(_pc_with_frame(6, 777)) == []
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert not hasattr(out[0], "frame")
