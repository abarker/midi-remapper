# example.py
#
# General-purpose example config file for midi_event_remapper.
# Load with:  midi-remapper example.py
# Validate:   midi-remapper --validate example.py
# List banks: midi-remapper --list-banks example.py
#
# This file is a plain Python dict literal -- a single dict (one BankSet)
# or a list of dicts (multiple BankSets).  No imports, no function calls,
# just data.  Comments use '#'.
#
# Chord keys use '+' notation: "CC1+CC2" instead of ("CC1", "CC2").
#
# Live reloading: midi-remapper watches this file for changes while
# running.  Edit and save; new mappings take effect within one second.
# The active bank is preserved across reloads.  Pass --no-reload to
# disable watching.
#
# ENTRY TYPE SUMMARY
# ------------------
# List value             -> direct: fires immediately on press and release
# Dict with "a" / "b"   -> toggle: alternates between two sequences
# Dict with any of       -> gesture: single / double / triple tap or long hold
#   single/double/
#   triple/long/repeat
# "CC1+CC2" key          -> chord: all keys must arrive within chord_window_ms
#
# See the README or config.py for the full schema.
#
# DEBUG LEVELS
# Two independent debug flags exist:
#   config.DEBUG (global)  -- controls dispatcher output: [in], [dispatch],
#                             and startup messages.  Set via the "debug" key
#                             in the global settings block below, or with
#                             --debug on the command line.
#   BankSet._debug         -- controls BankSet internals: gesture timing,
#                             chord windows, sequence dispatch detail.
#                             Set via "debug": True inside a BankSet dict.
#   --debug CLI flag       -- sets both levels simultaneously.

[

# ==========================================================================
# Global settings block (optional, list format only).
# Must be the first item in the list and must not have a "banks" key.
# Hot-reloadable: changes take effect within one second without restart.
# ==========================================================================
# {
#     "debug": False,   # sets config.DEBUG (dispatcher-level output)
# },

# ==========================================================================
# BankSet 1 -- global: always-active mappings checked before all others.
# Events handled here are not offered to subsequent BankSets.  Useful for
# controller-wide utility buttons that should never be bank-dependent.
# ==========================================================================
{
    "name":        "global",
    "active_bank": "default",

    # Per-BankSet timing overrides (optional; fall back to global constants
    # in config.py when omitted).
    # "long_press_ms":         500,   # long-press threshold in ms
    # "multi_press_window_ms": 300,   # double/triple accumulation window in ms
    # "chord_window_ms":        80,   # chord detection window in ms
    # "debounce_ms":            60,   # toggle debounce window in ms
    # "debug":                 True,  # per-BankSet debug output override

    "banks": {
        "default": {
            # Visual style for the --display / --no-titlebar window when
            # this bank is active.  All keys are optional; omitted keys fall
            # back to the module defaults in bank_display.py.
            # "_display": {"bg": "#1a1a1a", "fg": "#ffffff"},

            # Add entries here that should be active regardless of what
            # bank the main BankSet is on.

            # Example: a dedicated record button that always works.
            # "CC20": [{"send": "CMD", "cmd": "jack_transport start"}],
        },
    },
},

# ==========================================================================
# BankSet 2 -- main: the primary mapping set with multiple banks.
# ==========================================================================
{
    "name":        "main",
    "active_bank": "default",

    # "long_press_ms":         500,
    # "multi_press_window_ms": 300,
    # "chord_window_ms":        80,
    # "debounce_ms":            60,
    # "debug":                 True,

    "banks": {

        # ------------------------------------------------------------------
        # Default bank
        # ------------------------------------------------------------------
        "default": {

            # Visual style for the --display / --no-titlebar window.
            # "_display" is stripped before MIDI mapping lookup; it does not
            # interfere with any event key.  All keys are optional.
            #   "bg"        -- background colour  (e.g. "#1a1a2e")
            #   "fg"        -- text colour        (e.g. "#e0e0ff")
            #   "font_size" -- bank-name font size in points  (e.g. 72)
            #   "width"     -- window width in pixels         (e.g. 400)
            #   "height"    -- window height in pixels        (e.g. 200)
            # "_display": {"bg": "#1a1a2e", "fg": "#e0e0ff"},

            # ── DIRECT ────────────────────────────────────────────────────
            #
            # Fires immediately on both press (CC=127 / NoteOn) and release
            # (CC=0 / NoteOff).  The incoming value is forwarded unchanged
            # unless overridden with "value".  "press_only" suppresses the
            # release.  Zero latency.

            # Transparent remap: both press and release forwarded.
            # "CC0": [{"send": "CC10"}],

            # Press only: release is suppressed.
            # "CC0": [{"send": "CC10", "press_only": True}],

            # Fixed value: always sends 127 on press, 0 on release.
            # "CC0": [{"send": "CC10", "value": 127}],

            # Multiple outputs from one button press.
            # "PC1": [
            #     {"send": "NOTE36", "velocity": 127},
            #     {"send": "CC10",   "value": 64},
            # ],

            # Drop an event entirely (empty list).
            # "PC5": [],

            # Note with automatic NoteOff after a delay.
            # "PC2": [
            #     {"send": "NOTE36"},
            #     {"send": "NOTE36", "note_off": True, "delay": 0.25},
            # ],

            # Delayed send (seconds).
            # "CC1": [{"send": "CC11", "value": 127, "delay": 0.1}],


            # ── TOGGLE ────────────────────────────────────────────────────
            #
            # Alternates between sequence "a" and sequence "b" on each press.
            # "debounce_ms" (optional) prevents rapid re-trigger.

            # Basic toggle.
            # "CC2": {
            #     "a": [{"send": "CC20", "value": 127}],
            #     "b": [{"send": "CC20", "value": 0}],
            # },

            # Toggle with custom debounce.
            # "CC2": {
            #     "a":           [{"send": "CC20", "value": 127}],
            #     "b":           [{"send": "CC20", "value": 0}],
            #     "debounce_ms": 80,
            # },

            # Toggle between two banks.
            # "CC2": {
            #     "a": [{"send": "BANK", "bank": "layer2"}],
            #     "b": [{"send": "BANK", "bank": "default"}],
            # },


            # ── GESTURE ───────────────────────────────────────────────────
            #
            # Any combination of single / double / triple / long / repeat.
            # "long" and "repeat" require a momentary input (CC or NOTE) --
            # they are not valid for PC keys.  "long" and "repeat" are
            # mutually exclusive.

            # Single only -- fires immediately, zero latency.  Press-only.
            # "CC3": {
            #     "single": [{"send": "CC30", "value": 127}],
            # },

            # Multi-press -- incurs multi_press_window_ms delay on every press.
            # "CC3": {
            #     "single": [{"send": "CC30", "value": 127}],
            #     "double": [{"send": "CC31", "value": 127}],
            #     "triple": [{"send": "CC32", "value": 127}],
            # },

            # Multi-press with a tighter per-key window.
            # "CC3": {
            #     "single":   [{"send": "CC30", "value": 127}],
            #     "double":   [{"send": "CC31", "value": 127}],
            #     "multi_ms": 150,
            # },

            # Long press -- tap fires "single", hold fires "long" at threshold.
            # "long" fires immediately when the hold duration is reached;
            # no need to release first.
            # "CC3": {
            #     "single":  [{"send": "CC30", "value": 127}],
            #     "long":    [{"send": "PC1"}],
            #     "long_ms": 400,   # optional per-key override of long_press_ms
            # },

            # Long + multi-press combined.  The multi window starts after a
            # quick release so the two timing dimensions compose cleanly.
            # "CC3": {
            #     "single":  [{"send": "CC30", "value": 127}],
            #     "double":  [{"send": "CC31", "value": 127}],
            #     "long":    [{"send": "PC1"}],
            #     "long_ms": 400,
            # },

            # Hold-repeat -- fires "single" on quick tap; fires "repeat"
            # continuously while held (after repeat_delay_ms, then every
            # repeat_ms).  "long" and "repeat" are mutually exclusive.
            # "CC3": {
            #     "single":           [{"send": "CC30", "value": 127}],
            #     "repeat":           [{"send": "CC30", "value": 127}],
            #     "repeat_delay_ms":  400,   # ms before first repeat fires
            #     "repeat_ms":        80,    # ms between subsequent repeats
            # },

            # Repeat-only (no single action on quick tap).
            # "CC3": {
            #     "repeat":          [{"send": "CC30", "value": 127}],
            #     "repeat_delay_ms": 300,
            #     "repeat_ms":       100,
            # },

            # Gesture on a NOTE key (works identically to CC).
            # "NOTE60": {
            #     "single": [{"send": "CC30", "value": 127}],
            #     "long":   [{"send": "CC31", "value": 127}],
            # },

            # Gesture on a PC key (single / double / triple only -- no long
            # or repeat, since PC events have no release signal).
            # "PC4": {
            #     "single": [{"send": "CC30", "value": 127}],
            #     "double": [{"send": "CC31", "value": 127}],
            # },

            # Trigger value filter -- only dispatch when the incoming value
            # matches.  If it does not match, the event passes through.
            # Use [] as the sequence to drop non-matching events instead.
            # "CC3": {
            #     "trigger_value": "64-127",   # range
            #     # "trigger_value": 127,       # exact
            #     # "trigger_value": ">64",     # greater than
            #     # "trigger_value": "<=64",    # less than or equal
            #     # "trigger_value": [1, "64-127"],  # OR list
            #     "single": [{"send": "CC30", "value": 127}],
            # },


            # ── CHORD ─────────────────────────────────────────────────────
            #
            # All keys must arrive within chord_window_ms.  "long" is not
            # valid in chord entries.
            #
            # Fast chord (all CC/NOTE members): a solo press falls back with
            # near-zero latency because any member's release cancels the
            # window immediately.
            #
            # Standard chord (any PC member): always waits chord_window_ms
            # before falling back when the chord is incomplete.
            #
            # IMPORTANT: all labels for the same chord must be in a single
            # entry.  Python silently discards duplicate keys, so two entries
            # for "CC1+CC2" will lose the first one.

            # Fast chord: bank switch.
            # "CC4+CC5": {
            #     "single": [{"send": "BANK", "bank": "layer2"}],
            # },

            # Fast chord: bank switch + additional MIDI output.
            # "CC4+CC5": {
            #     "single": [
            #         {"send": "CC40", "value": 0},
            #         {"send": "BANK", "bank": "layer2"},
            #     ],
            # },

            # Fast chord: multi-press (two chord completions within
            # multi_press_window_ms fire "double").
            # "CC4+CC5": {
            #     "single": [{"send": "BANK", "bank": "layer2"}],
            #     "double": [{"send": "BANK", "bank": "layer3"}],
            # },

            # Standard chord using PC keys.
            # "PC4+PC5": {
            #     "single": [{"send": "CC40", "value": 127}],
            # },


            # ── CMD (shell command) ────────────────────────────────────────
            #
            # Runs in a background thread; does not block the MIDI handler.
            # stdout/stderr are printed when debug mode is active.
            # The shell is used, so pipes, redirects, and environment
            # variables all work.

            # "CC5": [{"send": "CMD", "cmd": "jack_transport start"}],

            # CMD combined with MIDI output.
            # "CC5": [
            #     {"send": "CC50", "value": 127},
            #     {"send": "CMD",  "cmd": "jack_transport start"},
            # ],

            # CMD on a gesture.
            # "CC5": {
            #     "single": [{"send": "CMD", "cmd": "jack_transport stop"}],
            #     "long":   [{"send": "CMD", "cmd": "jack_transport locate 0"}],
            # },

            # CMD on a chord.
            # "CC4+CC5": {
            #     "single": [
            #         {"send": "BANK", "bank": "layer2"},
            #         {"send": "CMD",  "cmd": "notify-send 'Bank: layer2'"},
            #     ],
            # },

        },  # end "default" bank

        # ------------------------------------------------------------------
        # Layer 2 bank
        # ------------------------------------------------------------------
        "layer2": {

            # "_display": {"bg": "#2e1a1a", "fg": "#ffb0a0", "font_size": 60},

            # Return to default.
            # "CC4+CC5": {
            #     "single": [{"send": "BANK", "bank": "default"}],
            # },

        },  # end "layer2" bank

        # ------------------------------------------------------------------
        # Layer 3 bank
        # ------------------------------------------------------------------
        "layer3": {

            # "_display": {"bg": "#1a2e1a", "fg": "#a0ffb0",
            #              "width": 500, "height": 200},

            # Return to default.
            # "CC4+CC5": {
            #     "single": [{"send": "BANK", "bank": "default"}],
            # },

        },  # end "layer3" bank

    },  # end "banks"

},  # end BankSet "main"

]  # end BankSet list
