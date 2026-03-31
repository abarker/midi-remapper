"""
config.py

User configuration: global constants and BankSet instances.

This is the file you edit to define your MIDI mappings.  It has no
mididings dependency and is importable without JACK running.

BANK / BANKSET SCHEMA
----------------------
Each bank is a flat dict.  The value shape determines the behaviour:

    List value             -> direct: fires immediately, no state
    Dict with a / b        -> toggle: alternates between two sequences
    Dict with tap / long   -> long press (momentary CC only):
                              tap fires on quick release,
                              long fires after long_ms
    Dict with single /     -> multi-press: accumulates presses within
      double / triple         MULTI_PRESS_WINDOW_MS then dispatches
    Tuple key              -> chord: all keys must arrive within
                              CHORD_WINDOW_MS

Sequence item format:

    Required:
        "send"     -- "PC<n>", "CC<n>", or "NOTE<n>"

    Optional (with defaults):
        "delay"    -- seconds before sending              (default 0.0)
        "value"    -- CC value 0-127, for CC sends        (default 127)
        "velocity" -- note velocity 0-127, for NOTE sends (default 127)
        "note_off" -- send NoteOff instead of NoteOn      (default False)

    Special send:
        "BANK"     -- switch this BankSet to another bank;
                      also requires "bank": "<bank_name>"

DATA_OFFSET NOTE
-----------------
DATA_OFFSET controls the numbering base for programs, ports, and
channels.  With DATA_OFFSET=1 (the default), program numbers run 1-128,
matching the labels on most hardware.  With DATA_OFFSET=0 they run
0-127, matching raw MIDI values.  Only program numbers (PC sends) are
affected; CC and NOTE numbers are always raw 0-127.  The validate()
method on each BankSet uses this value to catch out-of-range program
numbers at startup.
"""
from midi_event_remapper.bankset import BankSet

# --------------------------------------------------------------------------
# JACK / mididings connection settings
# --------------------------------------------------------------------------
BACKEND     = 'jack'
CLIENT_NAME = 'midi_event_remapper'
IN_PORT     = 'in_0'
OUT_PORT    = 'out_0'

# TODO: All output events are forced to a single channel by the Output()
# command in dispatcher.py.  Multi-channel output requires rethinking
# how Output() is used.
PORT_INDEX  = 1   # first port (with DATA_OFFSET=1)
CHANNEL     = 5   # forced output channel

# --------------------------------------------------------------------------
# Global timing and behaviour constants
# --------------------------------------------------------------------------

# See module docstring for DATA_OFFSET explanation.
DATA_OFFSET           = 1    # 1 = standard 1-indexed (channels 1-16, programs 1-128)

DEBOUNCE_MS           = 60   # default toggle debounce window (ms)
MULTI_PRESS_WINDOW_MS = 300  # window for double/triple press accumulation (ms)
CHORD_WINDOW_MS       = 80   # window within which chord keys must all arrive (ms)
LONG_PRESS_MS         = 500  # default long-press threshold (ms)

DEBUG                 = True

# --------------------------------------------------------------------------
# BankSet instances
# --------------------------------------------------------------------------
#
# The dispatcher checks BANK_SETS in order; the first BankSet that
# matches an incoming event handles it, and the rest are skipped.
#
# output_fn is intentionally left as None here; dispatcher.py sets it
# to engine.output_event on each BankSet before calling run().
#

actition_banks = BankSet(
    name                  = "actition",
    active_bank           = "default",
    debug                 = DEBUG,
    data_offset           = DATA_OFFSET,
    debounce_ms           = DEBOUNCE_MS,
    multi_press_window_ms = MULTI_PRESS_WINDOW_MS,
    chord_window_ms       = CHORD_WINDOW_MS,
    long_press_ms         = LONG_PRESS_MS,
    banks = {
        "default": {
            # Direct: single output
            # "PC5": [{"send": "NOTE36", "velocity": 127}],

            # Direct: multiple outputs
            # "PC6": [
            #     {"send": "NOTE38", "velocity": 127},
            #     {"send": "CC10",   "value": 64},
            # ],

            # Toggle
            # "CC22": {
            #     "a": [{"send": "CC40", "value": 127}],
            #     "b": [{"send": "CC40", "value": 0}],
            # },

            # Long press (momentary CC: sends 127 on press, 0 on release)
            # "CC30": {
            #     "tap":     [{"send": "PC1"}],
            #     "long":    [{"send": "PC2"}],
            #     "long_ms": 400,          # optional per-key override
            # },

            # Multi-press (incurs MULTI_PRESS_WINDOW_MS delay on every press)
            # "PC4": {
            #     "single": [{"send": "CC10", "value": 127}],
            #     "double": [{"send": "CC11", "value": 127}],
            #     "triple": [{"send": "CC12", "value": 127}],
            # },

            # Note on + note off after delay
            # "NOTE61": [
            #     {"send": "NOTE36"},
            #     {"send": "NOTE36", "note_off": True, "delay": 0.25},
            # ],

            # Chord -> bank switch + additional outputs
            # ("PC4", "PC5"): {
            #     "single": [
            #         {"send": "CC40", "value": 0},
            #         {"send": "BANK", "bank": "drums"},
            #     ],
            # },
            ("CC1", "CC2"): { "single": [{"send": "BANK", "bank": "drums"},],},

        },

        "drums": {
            # Chord -> switch back to default
            # ("PC4", "PC5"): {
            #     "single": [{"send": "BANK", "bank": "default"}],
            # },
            ("CC1", "CC2"): { "single": [{"send": "BANK", "bank": "default"},],},

            "CC0": [{"send": "CC4", "velocity": 127}],
            "CC1": [{"send": "CC5", "velocity": 127}],
            "CC2": [{"send": "CC6", "velocity": 127}],
            "CC3": [{"send": "CC7", "velocity": 127}],
        },
    },
)

# A BankSet with a single bank that never switches, useful for mappings
# that should always be active regardless of other BankSets' states.
global_banks = BankSet(
    name                  = "global",
    active_bank           = "default",
    debug                 = DEBUG,
    data_offset           = DATA_OFFSET,
    debounce_ms           = DEBOUNCE_MS,
    multi_press_window_ms = MULTI_PRESS_WINDOW_MS,
    chord_window_ms       = CHORD_WINDOW_MS,
    long_press_ms         = LONG_PRESS_MS,
    banks = {
        "default": {
            # Entries here are checked before actition_banks on every event.
        },
    },
)

BANK_SETS = [global_banks, actition_banks]
