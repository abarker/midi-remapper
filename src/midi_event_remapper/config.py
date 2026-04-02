"""
config.py

User configuration: global constants and BankSet instances.

This is the file you edit to define your MIDI mappings.  It has no
mididings dependency and is importable without JACK running.

BANK / BANKSET SCHEMA
----------------------
Each bank is a flat dict.  The value shape determines the behaviour:

    List value               -> direct: fires immediately, no state
    Dict with a / b          -> toggle: alternates between two sequences
    Dict with any of         -> gesture: unified handler covering all of:
      single/double/triple/     single press, double/triple press,
      long                      and long hold.  Any combination is valid.
    Tuple key                -> chord: all keys must arrive within
                                CHORD_WINDOW_MS.  Supports single/double/
                                triple just like gesture entries (see
                                CHORD ENTRIES below).

CHORD ENTRIES
--------------
A chord entry uses a tuple of event key strings as its dict key, and a
dict value containing any subset of "single", "double", "triple":

    ("CC1", "CC2"): {
        "single": [{"send": "BANK", "bank": "drums"}],
        "double": [{"send": "BANK", "bank": "ardour"}],
    },

"single" fires after one complete chord press within CHORD_WINDOW_MS.
"double" fires after two chord presses within MULTI_PRESS_WINDOW_MS.
"triple" fires after three chord presses within MULTI_PRESS_WINDOW_MS.
"long" is NOT valid in chord entries (chords have no individual release
signal); validate() will catch this at startup.

CRITICAL -- DUPLICATE TUPLE KEYS:
Python dicts silently discard duplicate keys.  If you define the same
chord tuple twice, only the last entry survives:

    ("CC1", "CC2"): {"single": [...]},  # WRONG: silently discarded!
    ("CC1", "CC2"): {"double": [...]},  # only this survives

Always combine all labels into a single entry:

    ("CC1", "CC2"): {
        "single": [...],
        "double": [...],
    },

The same applies to any other repeated key in a bank dict.

GESTURE ENTRIES
----------------
A gesture entry is a dict containing any subset of:

    "single"  -- sequence fired on a single press (or quick tap if 'long'
                 is also defined)
    "double"  -- sequence fired on two presses within MULTI_PRESS_WINDOW_MS
    "triple"  -- sequence fired on three presses within MULTI_PRESS_WINDOW_MS
    "long"    -- sequence fired when held past long_ms threshold.
                 Requires a momentary input (CC or NOTE) that sends a
                 release signal.  NOT valid for PC keys (no release signal).
    "long_ms" -- per-key long-press threshold in ms (default: LONG_PRESS_MS)
    "trigger_value" -- only dispatch when the incoming event value matches
                 (see TRIGGER VALUE below)

When 'long' is defined, 'single' behaves as a tap (fired on quick release).
When only 'single' is defined with no 'long' or multi variants, it fires
immediately on press with no timing delay.
When 'double' or 'triple' is defined, every press incurs a
MULTI_PRESS_WINDOW_MS delay before dispatching.

Examples:

    # Immediate single action (no delay)
    "CC0": {"single": [{"send": "CC10", "value": 127}]},

    # Long press: tap vs hold
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "long":   [{"send": "PC80"}],
        "long_ms": 300,
    },

    # Multi-press (incurs MULTI_PRESS_WINDOW_MS delay)
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "double": [{"send": "CC20", "value": 127}],
        "triple": [{"send": "CC30", "value": 127}],
    },

    # Combined: long + multi
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "double": [{"send": "CC20", "value": 127}],
        "long":   [{"send": "PC80"}],
        "long_ms": 300,
    },

    # Same for NOTE keys
    "NOTE60": {
        "single": [{"send": "CC10", "value": 127}],
        "long":   [{"send": "CC11", "value": 127}],
    },

TRIGGER VALUE
--------------
Any gesture or direct entry can include "trigger_value" to only dispatch
when the incoming event's data value matches a filter:

    "trigger_value": 127            # exact match
    "trigger_value": "64-127"       # inclusive range
    "trigger_value": ">64"          # greater than
    "trigger_value": "<64"          # less than
    "trigger_value": ">=64"         # greater than or equal
    "trigger_value": "<=64"         # less than or equal
    "trigger_value": [0, "64-127"]  # list: OR logic

If the incoming value does not match, the event passes through unchanged
(not dropped -- use an empty sequence [] to drop explicitly).

SEQUENCE ITEM FORMAT
---------------------
Each sequence is a list of dicts.  Required key: "send".

    Required:
        "send"       -- "PC<n>", "CC<n>", or "NOTE<n>"

    Optional (with defaults):
        "delay"      -- seconds before sending              (default 0.0)
        "value"      -- CC value 0-127, for CC sends.
                        If omitted, the incoming event's value is passed
                        through unchanged.  Useful for direct remaps where
                        you want both press and release forwarded.
                        Specify explicitly for gesture sequences where the
                        triggering event is a release (value=0):
                            "single": [{"send": "CC4", "value": 127}]
        "velocity"   -- note velocity 0-127, for NOTE sends (default 127)
        "note_off"   -- send NoteOff instead of NoteOn      (default False)
        "press_only" -- if True, skip this item on CC=0 or NoteOff release.
                        Only meaningful for direct mappings where both
                        press and release reach the sequence.
                        Not needed in gesture/toggle sequences (releases
                        are automatically suppressed for those types).

    Special send:
        "BANK"       -- switch this BankSet to another bank;
                        also requires "bank": "<bank_name>"

    Note: using "velocity" on a CC send or "value" on a NOTE send is a
    config error and will be caught by validate() at startup.

EMPTY SEND LISTS
-----------------
A mapping whose sequence is an empty list drops the event entirely:

    "PC5": [],   # PC5 is swallowed; nothing is sent downstream

Omitting a key passes the event through unchanged; using [] drops it.

FEATURES REQUIRING MOMENTARY (ON/OFF) EVENTS
----------------------------------------------
Some features depend on receiving both a press and a release signal.

For CC events, momentary means CC=127 on press and CC=0 on release.
For NOTE events, momentary means NoteOn on press and NoteOff on release.

Requires momentary:
    Gesture 'long' action
        Press timestamp is recorded; action dispatches on release.
        PC keys have no release signal and will be caught by validate().

    Fast chord -- tuple key where ALL members are CC or NOTE keys
        Any member's release cancels the chord window immediately,
        giving near-zero fallback latency.

Does NOT require momentary:
    Direct
        Both press and release are remapped by default.  Use "press_only"
        to suppress the release, or specify "value" to fix the output value.

    Toggle, gesture single/double/triple
        Press only; releases are automatically suppressed.

    Standard chord -- any PC member in the tuple key
        Press only; always waits out CHORD_WINDOW_MS before falling back.

"""
from midi_event_remapper.bankset import BankSet

# --------------------------------------------------------------------------
# JACK / mididings connection settings
# --------------------------------------------------------------------------
BACKEND     = 'jack'
CLIENT_NAME = 'mididings_event_remapper'
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

# DATA_OFFSET controls the numbering base for programs, ports, and channels.
# With DATA_OFFSET=1 (the default), program numbers run 1-128, matching the
# labels on most hardware.  With DATA_OFFSET=0 they run 0-127, matching raw
# MIDI values.  Only PC (program) numbers are affected; CC and NOTE numbers
# are always raw 0-127.  validate() uses this to catch out-of-range PC sends.
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
            # Direct: single output (both press and release are forwarded)
            # "PC5": [{"send": "NOTE36", "velocity": 127}],

            # Direct: single output, press only (release suppressed)
            # "CC5": [{"send": "CC10", "press_only": True}],

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

            # Gesture: single only -- fires immediately, no delay
            # "PC4": {
            #     "single": [{"send": "CC10", "value": 127}],
            # },

            # Gesture: multi-press -- incurs MULTI_PRESS_WINDOW_MS delay
            # "PC4": {
            #     "single": [{"send": "CC10", "value": 127}],
            #     "double": [{"send": "CC11", "value": 127}],
            #     "triple": [{"send": "CC12", "value": 127}],
            # },

            # Gesture: long press (momentary CC or NOTE only)
            # "CC30": {
            #     "single":  [{"send": "CC10", "value": 127}],
            #     "long":    [{"send": "PC1"}],
            #     "long_ms": 400,   # optional per-key override
            # },

            # Gesture: combined long + multi-press
            # "CC30": {
            #     "single":  [{"send": "CC10", "value": 127}],
            #     "double":  [{"send": "CC11", "value": 127}],
            #     "long":    [{"send": "PC1"}],
            #     "long_ms": 400,
            # },

            # Gesture: trigger only on specific value or range
            # "CC30": {
            #     "trigger_value": "64-127",
            #     "single": [{"send": "CC10", "value": 127}],
            # },

            # Note on + note off after delay
            # "NOTE61": [
            #     {"send": "NOTE36"},
            #     {"send": "NOTE36", "note_off": True, "delay": 0.25},
            # ],

            # Chord -> bank switch (fast chord: all CC keys)
            # ("CC4", "CC5"): {
            #     "single": [{"send": "BANK", "bank": "drums"}],
            # },

            # Chord -> bank switch + additional outputs (standard chord: PC keys)
            # ("PC4", "PC5"): {
            #     "single": [
            #         {"send": "CC40", "value": 0},
            #         {"send": "BANK", "bank": "drums"},
            #     ],
            # },
        },

        "drums": {
            # Chord -> switch back to default
            # ("CC4", "CC5"): {
            #     "single": [{"send": "BANK", "bank": "default"}],
            # },
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
