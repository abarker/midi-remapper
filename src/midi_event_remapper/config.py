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
    Dict with any of         -> gesture: unified handler covering single
      single/double/triple/     press, double/triple press, and long hold.
      long                      Any combination is valid.
    Tuple key                -> chord: all keys must arrive within
                                CHORD_WINDOW_MS.  Supports single/double/
                                triple (see CHORD ENTRIES below).

DIRECT vs GESTURE SINGLE -- WHICH TO USE?
-------------------------------------------
Direct and gesture-single may look similar but behave differently:

    DIRECT  "CC0": [{"send": "CC4"}]
        - Fires on BOTH press (CC=127) and release (CC=0).
        - The incoming value is forwarded unchanged by default, so the
          downstream device sees both the press and release signal.
        - Use "press_only": True to suppress the release.
        - Use "value": 127 to always send a fixed value.
        - Zero latency on press and release.
        - Best for: transparent CC remapping where you want the full
          press/release pair forwarded to the downstream device.

    GESTURE SINGLE  "CC0": {"single": [{"send": "CC4", "value": 127}]}
        - Fires on PRESS only; release is always suppressed.
        - You must specify "value" explicitly -- gesture sequences fire
          in response to the press event, so the value is always 127.
        - Zero latency (same as direct when no other labels defined).
        - Best for: press-only triggers, or when you plan to add
          "double"/"long" later without restructuring the entry.

    The latency of both is identical when only "single" is defined.
    The key difference is press-only vs press+release forwarding.

LATENCY GUIDE
--------------
Each feature type has different latency characteristics.  "Latency" here
means the delay between the physical button press and the output event.

    ZERO latency (fires immediately on press):
        Direct mapping
        Gesture with only "single" defined
        Toggle
        Chord completion (all keys arrived within CHORD_WINDOW_MS)

    CHORD_WINDOW_MS latency (default 80ms):
        Any key that is a member of a chord -- the press is held until
        either the chord completes or the window expires.
        Keys in fast chords (all CC/NOTE members) get near-zero latency
        on fallback because the window is cancelled on release.
        Keys in standard chords (any PC member) always wait the full
        CHORD_WINDOW_MS on fallback.

    MULTI_PRESS_WINDOW_MS latency (default 300ms):
        Gesture with "double" or "triple" defined -- every press waits
        for the window to expire before dispatching, including single
        presses.  If this latency is noticeable, reduce
        MULTI_PRESS_WINDOW_MS or consider using "long" instead of
        "double" for two-action keys (long has zero latency on press).
        Chord with "double" or "triple" defined -- same window applies
        to the first chord completion.

    Hold-duration latency (zero to LONG_PRESS_MS, default 500ms):
        Gesture with "long" defined -- the "long" action fires as soon
        as the hold threshold is reached (no need to release first).
        The "single" action fires on quick release.  Net latency for
        "single" is the physical hold duration, which is under user
        control.  Net latency for "long" is exactly long_ms.

    SUMMARY TABLE:
        Feature               | When output fires           | Latency
        ----------------------|-----------------------------|-------------------
        Direct                | Immediately on press        | ~0ms
        Gesture single-only   | Immediately on press        | ~0ms
        Toggle                | Immediately on press        | ~0ms
        Chord (complete)      | When last key arrives       | ~0ms
        Chord (fallback)      | After CHORD_WINDOW_MS       | 80ms (default)
        Fast chord fallback   | On key release              | ~0ms
        Gesture multi-press   | After MULTI_PRESS_WINDOW_MS | 300ms (default)
        Gesture long          | At long_ms threshold        | long_ms (hold)
        Gesture single+long   | On quick release            | hold duration
        Chord multi-press     | After MULTI_PRESS_WINDOW_MS | 300ms (default)
        Gesture repeat        | After repeat_delay_ms, then | repeat_delay_ms,
                              | every repeat_ms             | then repeat_ms
        Gesture single+repeat | On quick release (if no     | hold duration
                              | repeat yet fired)           |

GESTURE ENTRIES
----------------
A gesture entry is a dict containing any subset of:

    "single"  -- sequence fired on a single press (or quick tap if 'long'
                 or 'repeat' is also defined); fires immediately if no
                 other labels are defined alongside it
    "double"  -- sequence fired on two presses within MULTI_PRESS_WINDOW_MS
    "triple"  -- sequence fired on three presses within MULTI_PRESS_WINDOW_MS
    "long"    -- sequence fired at long_ms threshold (fires immediately
                 when threshold is reached, before release).  Requires a
                 momentary input (CC or NOTE); NOT valid for PC keys.
                 Mutually exclusive with 'repeat'.
    "repeat"  -- sequence fired repeatedly while the key is held.  First
                 fires after repeat_delay_ms, then every repeat_ms until
                 release.  If released before first repeat fires, treats
                 the press as a tap and fires 'single' if defined.
                 Requires a momentary input (CC or NOTE); NOT valid for
                 PC keys.  Mutually exclusive with 'long'.
    "long_ms"         -- hold threshold in ms (default: LONG_PRESS_MS)
    "multi_ms"        -- per-key multi-press window in ms, overrides
                         MULTI_PRESS_WINDOW_MS for this key only
    "repeat_delay_ms" -- hold time before first repeat fires (default: 500ms)
    "repeat_ms"       -- interval between subsequent repeats (default: 100ms)
    "trigger_value"   -- only dispatch when incoming event value matches
                         (see TRIGGER VALUE below)

When 'long' or 'repeat' is defined alongside 'double'/'triple', the
multipress window starts on quick release (not on press), so they compose
cleanly.

Examples:

    # Immediate single action (no delay, press-only)
    "CC0": {"single": [{"send": "CC10", "value": 127}]},

    # Long press: tap vs hold (long fires at threshold, no release needed)
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "long":   [{"send": "PC80"}],
        "long_ms": 300,
    },

    # Multi-press (incurs MULTI_PRESS_WINDOW_MS delay on every press)
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "double": [{"send": "CC20", "value": 127}],
        "triple": [{"send": "CC30", "value": 127}],
    },

    # Combined: long + multi (multipress window starts after quick release)
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

Fast vs standard chord (affects fallback latency only):
    Fast chord   -- ALL members are CC or NOTE keys: any member's release
                    cancels the chord window immediately, so a solo press
                    of a chord member falls back with near-zero latency.
    Standard chord -- any PC member: always waits CHORD_WINDOW_MS before
                    falling back when the chord is incomplete.

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

The same applies to any other repeated string key in a bank dict.

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
    "trigger_value": [1, "64-127"]  # list: OR logic (avoid 0: CC release)

If the incoming value does not match, the event passes through unchanged.
Use an empty sequence [] to drop it instead.

Note: "trigger_value": 0 is ambiguous for CC keys because CC=0 is also
the release signal.  For value-0 matching, use NOTE or PC keys instead.

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
                        you want both press and release forwarded:
                            "CC0": [{"send": "CC4"}]  # forwards 127 and 0
                        Specify explicitly in gesture sequences (which fire
                        on press, not release):
                            "single": [{"send": "CC4", "value": 127}]
        "velocity"   -- note velocity 0-127, for NOTE sends (default 127)
        "note_off"   -- send NoteOff instead of NoteOn      (default False)
        "press_only" -- if True, skip this item on CC=0 or NoteOff release.
                        Only meaningful for DIRECT mappings where both
                        press and release reach the sequence.
                        Not needed in gesture/toggle sequences (releases
                        are automatically suppressed for those types).

    Special sends:
        "BANK"       -- switch this BankSet to another bank;
                        also requires "bank": "<bank_name>"
        "CMD"        -- run a shell command in a background thread.
                        Also requires "cmd": "<shell command string>".
                        Non-blocking: the MIDI handler returns immediately.
                        stdout/stderr are printed in debug mode.
                        The command is run via the shell, so pipes,
                        redirects, and environment variables all work.

                        Examples:
                            {"send": "CMD", "cmd": "jack_transport start"}
                            {"send": "CMD", "cmd": "jack_transport locate 0"}
                            {"send": "CMD", "cmd": "aconnect 14:0 128:0"}
                            {"send": "CMD", "cmd": "echo 120 > /tmp/bpm.txt"}

                        CMD items can be combined with MIDI sends in the
                        same sequence:
                            [
                                {"send": "CC10", "value": 127},
                                {"send": "CMD",  "cmd": "jack_transport start"},
                            ]

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
        Press timestamp is recorded on CC=127/NoteOn; the long threshold
        timer fires at long_ms and the release is then suppressed.
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
