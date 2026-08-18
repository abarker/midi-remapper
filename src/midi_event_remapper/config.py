"""config.py

Global constants and runtime state for midi_event_remapper.

BankSets are no longer defined here.  Pass one or more ``.py`` config
files on the command line instead::

    midi-remapper mycontroller.py
    midi-remapper global.py mycontroller.py

This file sets the JACK connection parameters, global timing constants,
and the two debug flags.  Edit it to change defaults; all settings can
also be overridden on the command line.

DEBUG LEVELS
------------
Two independent debug flags control output:

``DEBUG`` (global, this file)
    Controls dispatcher-level output: the ``[in]``, ``[dispatch]``, and
    startup lines printed by ``dispatcher.py``.  Override with ``--debug``
    or set ``"debug": True`` in the global settings block of a config file
    (hot-reloadable).

``BankSet._debug`` (per-BankSet)
    Controls BankSet-level detail: gesture timing, chord windows, sequence
    dispatch.  Set per-BankSet via ``"debug": True`` inside a BankSet dict
    in a config file.  Override for all BankSets with ``--debug``.

The ``--debug`` CLI flag sets both levels simultaneously.

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
        Gesture eager_single  | Immediately on press        | ~0ms (single fires
          + long/double/repeat|                             | at press; deferred
                              |                             | label fires later)
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
    "eager_single"    -- bool (default False); if True, fire the 'single'
                         sequence immediately on the first press instead of
                         waiting for the gesture to resolve.  The deferred
                         action ('long', 'double', 'triple', 'repeat') still
                         fires normally in addition.  Zero latency for
                         'single' while keeping all other gesture labels.
                         Has no effect (and generates a warning) if no
                         deferred label is defined alongside 'single'.
                         A 'BANK' send inside an eager 'single' sequence is
                         a validation error (see §7 of EAGER_SINGLE_PLAN).

When 'long' or 'repeat' is defined alongside 'double'/'triple', the
multipress window starts on quick release (not on press), so they compose
cleanly.

CHORD ENTRIES
--------------
A chord entry uses a tuple of event key strings as its dict key, and a
dict value containing any subset of "single", "double", "triple":

    ("CC1", "CC2"): {
        "single": [{"send": "BANK", "bank": "drums"}],
        "double": [{"send": "BANK", "bank": "ardour"}],
    },

"long" is NOT valid in chord entries; validate() catches this at startup.

CRITICAL -- DUPLICATE TUPLE KEYS:
Python dicts silently discard duplicate keys.  Always combine all labels
into a single entry:

    ("CC1", "CC2"): {
        "single": [...],
        "double": [...],
    },

TRIGGER VALUE
--------------
Any gesture or direct entry can include "trigger_value":

    "trigger_value": 127            # exact match
    "trigger_value": "64-127"       # inclusive range
    "trigger_value": ">64"          # greater than
    "trigger_value": [1, "64-127"]  # list: OR logic (avoid 0: CC release)

SEQUENCE ITEM FORMAT
---------------------
Each sequence is a list of dicts.  Required key: "send".

    {"send": "CC<n>",   "value": 127, "press_only": True,  "delay": 0.0}
    {"send": "PC<n>"}
    {"send": "NOTE<n>", "velocity": 127, "note_off": False}
    {"send": "BANK",    "bank": "drums"}
    {"send": "CMD",     "cmd": "jack_transport start", "delay": 0.0}

Note: using "velocity" on a CC send or "value" on a NOTE send is caught
by validate() at startup.
"""
import sys

# --------------------------------------------------------------------------
# JACK / mididings connection settings
# --------------------------------------------------------------------------
BACKEND     = 'jack'
CLIENT_NAME = 'midi_remapper'
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
# labels on most hardware.  With DATA_OFFSET=0 they run 0-127 (raw MIDI).
DATA_OFFSET           = 1

DEBOUNCE_MS           = 60   # default toggle debounce window (ms)
MULTI_PRESS_WINDOW_MS = 300  # window for double/triple press accumulation (ms)
CHORD_WINDOW_MS       = 80   # window within which chord keys must all arrive (ms)
LONG_PRESS_MS         = 500  # default long-press threshold (ms)

# --------------------------------------------------------------------------
# Debug flags (see module docstring for the two-level debug system)
# --------------------------------------------------------------------------

# Dispatcher-level debug: [in], [dispatch], and startup messages.
# Set True here, use --debug on the CLI, or add "debug": True to the global
# settings block of a config file (the config file setting is hot-reloadable).
DEBUG = False

# --------------------------------------------------------------------------
# Runtime state -- populated by dispatcher.py at startup
# --------------------------------------------------------------------------

# BankSets loaded from config files.  Replaced atomically by the reloader
# on each successful hot reload.  Empty until cli.py loads the config files.
BANK_SETS = []


# --------------------------------------------------------------------------
# Output helper
# --------------------------------------------------------------------------

def urgent_print(msg):
    """Print a message that must be seen at once, not when the buffer fills.

    Writes to **both** streams:

    * stdout -- the session log when output is redirected, flushed so the
      log keeps its chronological order and stays complete.
    * stderr -- reaches the console, and Python keeps stderr line buffered
      even when it is not a tty, so it appears immediately.

    Redirecting stdout to a file makes Python block buffer it (8 KB), which
    is what keeps ordinary tracing off the syscall path in the ``--jack-rt``
    callback.  The cost is that a message can sit unwritten for a long time
    -- and with debug off the log is quiet enough that a rejected config
    reload could stay invisible for days.  This routine is the exception
    for the messages where that is unacceptable.

    Use for faults and reload results only.  High-volume tracing must keep
    plain ``print``.  Calls from the RT callback are acceptable because the
    sites that use it fire only when something has already gone wrong, so
    the flush is never paid during normal operation.
    """
    print(msg, flush=True)
    print(msg, file=sys.stderr)
