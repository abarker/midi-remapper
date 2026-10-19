"""
midi.py

Low-level MIDI utilities: event key extraction and event construction.
These functions are the only place in the package that import mididings
types directly.  The mididings module is expected to be present in
sys.modules before this module is imported; in tests, conftest.py injects
a mock before any package imports occur.

When the optional Cython extension ``midi_event_remapper.midi_core`` has
been built, the three hot-path functions are imported from it.  Otherwise
the pure-Python implementations defined below are used transparently.
Build the extension with::

    pip install ".[rt]"
    python setup.py build_ext --inplace

``_CYTHON_CORE`` is a module-level bool that callers (e.g. cli.py) can
inspect to determine which implementation is active.
"""
from mididings import PROGRAM, CTRL, NOTEON, NOTEOFF
from mididings.event import (
    ProgramEvent, CtrlEvent, NoteOnEvent, NoteOffEvent, SysExEvent,
)

# ---------------------------------------------------------------------------
# Cython fast path -- transparently replace the three hot-path functions
# when the compiled extension is available.
# ---------------------------------------------------------------------------
import os as _os
_CYTHON_CORE = False
if not _os.environ.get("MIDI_REMAPPER_NO_CYTHON"):
    try:
        from midi_event_remapper.midi_core import (   # noqa: F811
            event_key, is_release, build_event,
        )
        _CYTHON_CORE = True
    except ImportError:
        pass


if not _CYTHON_CORE:

    def event_key(event):
        """Return the canonical string key for a mididings event.

        Returns one of:
            'PC<n>'    for program-change events
            'CC<n>'    for control-change events (including CC=0 releases)
            'NOTE<n>'  for note-on AND note-off events
            None       for any other event type

        Both NoteOn and NoteOff map to the same key so that gesture handling
        (long press, double tap) works symmetrically for note-based buttons.
        CC=0 and NoteOff are distinguished by is_release() rather than by key.
        """
        if event.type == PROGRAM:
            return f"PC{event.program}"
        elif event.type == CTRL:
            return f"CC{event.ctrl}"
        elif event.type in (NOTEON, NOTEOFF):
            return f"NOTE{event.note}"
        return None


    def is_release(event):
        """Return True if this event is a release signal.

        Release signals are:
            CC events with value == 0  (momentary CC release)
            NoteOff events             (note release)

        Used by BankSet to route events to gesture release handling.
        """
        if event.type == CTRL:
            return getattr(event, 'value', 0) == 0
        if event.type == NOTEOFF:
            return True
        return False


    def build_event(item, port, channel, event_value=None):
        """Build a single mididings output event from a sequence item dict.

        Required key:
            'send'     -- 'PC<n>', 'CC<n>', or 'NOTE<n>'

        Optional keys (with defaults):
            'delay'    -- seconds before sending              (default 0.0)
            'channel'  -- MIDI channel for the outgoing event; if omitted
                          the incoming event's channel is passed through.
            CC sends:   'value'    -- CC value 0-127.
                                      If omitted, the incoming event's value
                                      is passed through (event_value).
            NOTE sends: 'velocity' -- note velocity 0-127     (default 127)
                        'note_off' -- send NoteOff if True     (default False)
            PC sends:   (no extra keys needed)

        Using 'velocity' on a CC send or 'value' on a NOTE send is a config
        error caught by validate() at startup.

        'BANK' sends are handled by BankSet._execute_sequence before reaching
        this function and will raise ValueError if passed in here.
        """
        send = item["send"]
        out_channel = item.get("channel", channel)   # override or pass through
        if send.startswith("CC"):
            if "value" in item:
                value = int(item["value"])
            elif event_value is not None:
                value = int(event_value)
            else:
                value = 127
            return CtrlEvent(port, out_channel, int(send[2:]), value)
        elif send.startswith("PC"):
            return ProgramEvent(port, out_channel, int(send[2:]))
        elif send.startswith("NOTE"):
            n        = int(send[4:])
            velocity = int(item.get("velocity", 127))
            if item.get("note_off"):
                return NoteOffEvent(port, out_channel, n, velocity)
            return NoteOnEvent(port, out_channel, n, velocity)
        elif send == "SYSEX":
            sx = item["sysex"]
            return SysExEvent(port, bytes(sx) if isinstance(sx, list) else sx)
        else:
            raise ValueError(f"build_event: unhandled send value {send!r}")


# ---------------------------------------------------------------------------
# --keep-offsets (experimental, off by default): keep each remapped event
# at its input's position within the JACK period.
#
# mididings keeps each event's frame (its sample time) on the C++ event and
# writes an output event at the frame it carries, but does not expose the
# frame to Python, and events built in Python (build_event above) have
# frame 0, so they go out at the start of the period.  Two functions in
# mididings' extension module carry the frame: midi_event_to_buffer(ev)
# returns (bytes, port, frame), and buffer_to_midi_event(bytes, port,
# frame) builds an event with it.  They are undocumented, though mididings'
# own engine.py uses them, so enable_keep_offsets() checks that they exist
# and round-trip a frame before anything relies on them.  The event they
# build is the plain extension type; mididings' Process() calls
# _finalize() on every returned event, so with_frame() gives it the full
# mididings.event.MidiEvent class the same way mididings itself does for
# incoming events (``ev.__class__ = MidiEvent`` in units/call.py).
# ---------------------------------------------------------------------------
KEEP_OFFSETS = False
_to_buffer   = None
_from_buffer = None
_event_class = None


def enable_keep_offsets(backend):
    """Turn on --keep-offsets.  Returns None on success, otherwise the
    reason it stays off (the remapper then runs exactly as without it)."""
    global KEEP_OFFSETS, _to_buffer, _from_buffer, _event_class
    if backend not in ("jack", "jack-rt"):
        return f"only the JACK backends have sample offsets (backend: {backend})"
    try:
        import _mididings as mod
    except ImportError:
        return "mididings' _mididings extension module was not found"
    to_buffer   = getattr(mod, "midi_event_to_buffer", None)
    from_buffer = getattr(mod, "buffer_to_midi_event", None)
    if to_buffer is None or from_buffer is None:
        return ("this mididings has no midi_event_to_buffer / "
                "buffer_to_midi_event")
    import importlib
    event_class = getattr(importlib.import_module("mididings.event"),
                          "MidiEvent", None)
    if event_class is None:
        return "this mididings has no mididings.event.MidiEvent"
    try:
        data, port, _ = to_buffer(CtrlEvent(1, 2, 3, 4))
        moved = from_buffer(bytes(data), port, 123457)
        moved.__class__ = event_class
        moved._finalize()          # what Process() does to each output
        back = to_buffer(moved)
        if (list(back[0]), back[1], back[2]) != (list(data), port, 123457):
            return f"self-test failed: got {back!r}"
    except Exception as e:  # noqa: BLE001 -- any failure means "stay off"
        return f"self-test failed: {e!r}"
    _to_buffer, _from_buffer, _event_class = to_buffer, from_buffer, event_class
    KEEP_OFFSETS = True
    return None


def frame_of(event):
    """The frame (sample time) an incoming event carries."""
    return _to_buffer(event)[2]


def with_frame(event, frame):
    """A copy of an output event that carries the given frame."""
    data, port, _ = _to_buffer(event)
    moved = _from_buffer(bytes(data), port, frame)
    moved.__class__ = _event_class
    return moved
