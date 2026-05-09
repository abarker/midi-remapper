# midi_core.pyx
# cython: language_level=3, boundscheck=False, wraparound=False, nonecheck=False
"""Cython-compiled inner-loop functions for midi_event_remapper.

These replace the pure-Python equivalents in midi.py when the
extension has been built (``pip install ".[rt]"`` then
``python setup.py build_ext --inplace``).

Phase 1 (this file): conservative annotation.  C-typed local
variables eliminate repeated Python attribute lookup and dynamic
dispatch overhead on the hot path.  All functions still hold the
GIL because mididings event attributes and string construction
are Python-level operations.

Phase 2 (future): cache the mididings integer constants as
module-level C ints; restructure build_event() to minimise Python
object creation; introduce ``nogil`` sections for the scalar
classification logic.

Logic is identical to the pure-Python fallbacks in midi.py.
"""

from mididings import PROGRAM, CTRL, NOTEON, NOTEOFF
from mididings.event import (
    ProgramEvent, CtrlEvent, NoteOnEvent, NoteOffEvent, SysExEvent,
)


cpdef str event_key(object event):
    """Return the canonical string key for a mididings event.

    Returns ``'PC<n>'``, ``'CC<n>'``, ``'NOTE<n>'``, or ``None``.

    Called on every incoming MIDI event -- the single hottest call site
    in the entire package.  Storing ``event.type`` once as a C int
    avoids three repeated Python attribute lookups in the common case.
    """
    cdef int etype = event.type
    cdef int n

    if etype == CTRL:
        n = event.ctrl
        return f"CC{n}"
    if etype == PROGRAM:
        n = event.program
        return f"PC{n}"
    if etype == NOTEON or etype == NOTEOFF:
        n = event.note
        return f"NOTE{n}"
    return None


cpdef bint is_release(object event):
    """Return True if event is a CC=0 or NoteOff release signal.

    ``bint`` compiles to a C int (0/1), avoiding a Python bool object
    on the return path.
    """
    cdef int etype = event.type
    if etype == CTRL:
        return event.value == 0
    return etype == NOTEOFF


cpdef object build_event(object item, int port, int channel,
                         object event_value=None):
    """Build a single mididings output event from a sequence item dict.

    ``port`` and ``channel`` are C ints, avoiding Python int object
    creation on every call.  The mididings event constructors are
    Python-level calls so the GIL is always held; the gain here is
    in the branching and arithmetic, not in GIL release.

    Branch logic is identical to the pure Python version in midi.py so
    both implementations are straightforward to compare and verify.
    """
    cdef int n, val, vel
    cdef str send = item["send"]

    if send.startswith("CC"):
        if "value" in item:
            val = <int>item["value"]
        elif event_value is not None:
            val = <int>event_value
        else:
            val = 127
        n = int(send[2:])
        return CtrlEvent(port, channel, n, val)

    if send.startswith("PC"):
        n = int(send[2:])
        return ProgramEvent(port, channel, n)

    if send.startswith("NOTE"):
        n   = int(send[4:])
        vel = <int>item.get("velocity", 127)
        if item.get("note_off"):
            return NoteOffEvent(port, channel, n, vel)
        return NoteOnEvent(port, channel, n, vel)

    if send == "SYSEX":
        sx = item["sysex"]
        return SysExEvent(port, bytes(sx) if isinstance(sx, list) else sx)

    raise ValueError(f"build_event: unhandled send value {send!r}")
