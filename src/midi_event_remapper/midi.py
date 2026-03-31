"""
midi.py

Low-level MIDI utilities: event key extraction and event construction.
These functions are the only place in the package that import mididings
types directly.  The mididings module is expected to be present in
sys.modules before this module is imported; in tests, conftest.py injects
a mock before any package imports occur.
"""
from mididings import PROGRAM, CTRL, NOTEON
from mididings.event import (
    ProgramEvent, CtrlEvent, NoteOnEvent, NoteOffEvent, SysExEvent,
)


def event_key(event):
    """Return the canonical string key for a mididings event.

    Returns one of:
        'PC<n>'    for program-change events
        'CC<n>'    for control-change events (including CC=0 releases)
        'NOTE<n>'  for note-on events
        None       for any other event type

    CC=0 release events intentionally receive a key so that the
    long-press machinery in BankSet can intercept them.
    """
    if event.type == PROGRAM:
        return f"PC{event.program}"
    elif event.type == CTRL:
        return f"CC{event.ctrl}"
    elif event.type == NOTEON:
        return f"NOTE{event.note}"
    return None


def build_event(item, port, channel, event_value=None):
    """Build a single mididings output event from a sequence item dict.

    Required key:
        'send'     -- 'PC<n>', 'CC<n>', or 'NOTE<n>'

    Optional keys (with defaults):
        'delay'    -- seconds before sending              (default 0.0)
        CC sends:   'value'    -- CC value 0-127
                                  if omitted, the incoming event's value
                                  is passed through (event_value); if that
                                  is also absent, defaults to 127
        NOTE sends: 'velocity' -- note velocity 0-127     (default 127)
                    'note_off' -- send NoteOff if True     (default False)
        PC sends:   (no extra keys needed)

    'BANK' sends are handled by BankSet._execute_sequence before reaching
    this function and will raise ValueError if passed in here.
    """
    send = item["send"]
    if send.startswith("CC"):
        if "value" in item:
            value = int(item["value"])
        elif event_value is not None:
            value = int(event_value)
        else:
            value = 127
        return CtrlEvent(port, channel, int(send[2:]), value)
    elif send.startswith("PC"):
        return ProgramEvent(port, channel, int(send[2:]))
    elif send.startswith("NOTE"):
        n        = int(send[4:])
        velocity = int(item.get("velocity", 127))
        if item.get("note_off"):
            return NoteOffEvent(port, channel, n, velocity)
        return NoteOnEvent(port, channel, n, velocity)
    elif send == "SYSEX":
        sx = item["sysex"]
        return SysExEvent(port, bytes(sx) if isinstance(sx, list) else sx)
    else:
        raise ValueError(f"build_event: unhandled send value {send!r}")
