"""
testing.py

Test helper factories shared between conftest.py and test modules.
Lives in the main package so it is importable without sys.path tricks.
Not imported by any production code.
"""
from midi_event_remapper.mock_mididings import FakeInputEvent, NOTEOFF
from midi_event_remapper.bankset import BankSet


def make_pc(program, port=1, channel=1):
    return FakeInputEvent("PROGRAM", port=port, channel=channel,
                          program=program)


def make_cc(ctrl, value=127, port=1, channel=1):
    return FakeInputEvent("CTRL", port=port, channel=channel,
                          ctrl=ctrl, value=value)


def make_note(note, velocity=127, port=1, channel=1):
    return FakeInputEvent("NOTEON", port=port, channel=channel,
                          note=note, velocity=velocity)


def make_noteoff(note, velocity=0, port=1, channel=1):
    return FakeInputEvent(NOTEOFF, port=port, channel=channel,
                          note=note, velocity=velocity)


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
