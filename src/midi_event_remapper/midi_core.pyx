# midi_core.pyx
# cython: language_level=3, boundscheck=False, wraparound=False, nonecheck=False
"""Cython-compiled inner-loop functions for midi_event_remapper.

These replace the pure-Python equivalents in midi.py when the
extension has been built (``pip install ".[rt]"`` then
``python setup.py build_ext --inplace``).

Phase 1 added C-typed local variables to eliminate repeated Python
attribute lookup and dynamic dispatch on the hot path.

Phase 2 (this file) adds:

- Module-level ``cdef int`` constants for the mididings event type
  integers, making every event-type comparison a pure C integer
  operation with no Python equality protocol or type dispatch.

- ``cdef inline nogil`` helper functions containing the pure C
  classification logic.  These are callable from any future ``nogil``
  context without modification, and serve as the foundation for
  Phase 3 (a C-struct event representation that eliminates Python
  attribute access on the hot path entirely).

- ``is_release()`` and ``event_key()`` each extract C int values from
  the Python event object (GIL required), then delegate to the
  ``nogil`` helpers for the pure logic.

All functions are behaviourally identical to the pure-Python fallbacks
in midi.py.  Logic is parallel so both implementations are easy to
compare and verify.
"""

from mididings.event import (
    ProgramEvent, CtrlEvent, NoteOnEvent, NoteOffEvent, SysExEvent,
)
from mididings import CTRL    as _CTRL_PY, \
                      NOTEON  as _NOTEON_PY, \
                      NOTEOFF as _NOTEOFF_PY, \
                      PROGRAM as _PROGRAM_PY

# ---------------------------------------------------------------------------
# Module-level C integer constants.
# Initialised once from the mididings Python constants at module load.
# After this point every event-type comparison in this file is a pure
# C integer operation: no Python object is consulted, no equality
# protocol is invoked, no type dispatch occurs.
# ---------------------------------------------------------------------------
cdef int _CTRL    = _CTRL_PY
cdef int _NOTEON  = _NOTEON_PY
cdef int _NOTEOFF = _NOTEOFF_PY
cdef int _PROGRAM = _PROGRAM_PY


# ---------------------------------------------------------------------------
# GIL-free classification helpers.
# cdef inline nogil: inlined by the compiler, zero call overhead,
# callable from any future nogil context.
# ---------------------------------------------------------------------------

cdef inline int _classify_etype(int etype) nogil:
    """Map a raw mididings event type integer to a classification code.

    Returns:
        1  CC / control-change
        2  NOTE (NoteOn or NoteOff -- same key; release handled separately)
        3  PC / program-change
        0  unknown / unhandled
    """
    if etype == _CTRL:
        return 1
    if etype == _NOTEON or etype == _NOTEOFF:
        return 2
    if etype == _PROGRAM:
        return 3
    return 0


cdef inline bint _is_release_impl(int etype, int value) nogil:
    """Return True if the pre-extracted fields indicate a release event.

    Called by is_release() after extracting C int values from the Python
    event object.  Pure C logic: no GIL required.
    """
    if etype == _CTRL:
        return value == 0
    return etype == _NOTEOFF


# ---------------------------------------------------------------------------
# Public API (cpdef: callable from Python and from Cython at C speed)
# ---------------------------------------------------------------------------

cpdef str event_key(object event):
    """Return the canonical string key for a mididings event.

    Returns ``'PC<n>'``, ``'CC<n>'``, ``'NOTE<n>'``, or ``None``.

    Extracts ``event.type`` (GIL required -- Python attribute access),
    passes it to ``_classify_etype()`` (nogil C classification), then
    accesses the specific attribute and builds the string (GIL required).
    """
    cdef int etype = event.type
    cdef int code  = _classify_etype(etype)
    cdef int n

    if code == 1:
        n = event.ctrl
        return f"CC{n}"
    if code == 3:
        n = event.program
        return f"PC{n}"
    if code == 2:
        n = event.note
        return f"NOTE{n}"
    return None


cpdef bint is_release(object event):
    """Return True if event is a CC=0 or NoteOff release signal.

    Extracts the C int fields needed, then delegates to
    ``_is_release_impl()`` (nogil) for the pure C logic.
    ``bint`` compiles to a C int (0/1), avoiding a Python bool on return.
    """
    cdef int etype = event.type
    cdef int value = 0
    if etype == _CTRL:
        value = event.value
    return _is_release_impl(etype, value)


cpdef object build_event(object item, int port, int channel,
                         object event_value=None):
    """Build a single mididings output event from a sequence item dict.

    ``port`` and ``channel`` are C ints.  Branch logic uses
    ``str.startswith()`` for readability and safety, identical to
    the pure Python version in midi.py.
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
