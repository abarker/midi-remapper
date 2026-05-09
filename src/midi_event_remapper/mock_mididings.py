"""
mock_mididings.py

Minimal mididings stub for use in tests.  Injected into sys.modules by
conftest.py before any package imports occur, so midi.py's normal
'from mididings import ...' calls receive these objects instead.
"""

# Event type constants -- integer values, matching real mididings' bit-flag
# convention.  Integer types are required for compatibility with the Cython
# extension, which stores event.type as a C int (cdef int etype).
NOTEON  = 1
NOTEOFF = 2
CTRL    = 4
PROGRAM = 8


class FakeOutputEvent:
    """Represents a mididings output event built by build_event()."""
    def __init__(self, kind, **kwargs):
        self.kind = kind
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        attrs = ", ".join(
            f"{k}={v!r}" for k, v in self.__dict__.items()
        )
        return f"FakeOutputEvent({attrs})"

    def __eq__(self, other):
        return isinstance(other, FakeOutputEvent) and \
               self.__dict__ == other.__dict__


def CtrlEvent(port, channel, ctrl, value):
    return FakeOutputEvent(
        "CC", port=port, channel=channel, ctrl=ctrl, value=value
    )

def ProgramEvent(port, channel, program):
    return FakeOutputEvent(
        "PC", port=port, channel=channel, program=program
    )

def NoteOnEvent(port, channel, note, velocity):
    return FakeOutputEvent(
        "NOTEON", port=port, channel=channel, note=note, velocity=velocity
    )

def NoteOffEvent(port, channel, note, velocity):
    return FakeOutputEvent(
        "NOTEOFF", port=port, channel=channel, note=note, velocity=velocity
    )

def SysExEvent(port, data):
    return FakeOutputEvent("SYSEX", port=port, data=data)


class engine:
    """Stub for mididings.engine."""
    @staticmethod
    def output_event(ev):
        pass  # overridden per-test via BankSet.set_output_fn()


class FakeInputEvent:
    """Represents an incoming mididings event for use in tests."""
    def __init__(self, type_, port=1, channel=1, **kwargs):
        self.type    = type_
        self.port    = port
        self.channel = channel
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        attrs = ", ".join(
            f"{k}={v!r}" for k, v in self.__dict__.items()
        )
        return f"FakeInputEvent({attrs})"
