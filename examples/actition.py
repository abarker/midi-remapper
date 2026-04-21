# actition.py
#
# Example BankSet config file for the Actition controller.
# Load with:  midi-remapper actition.py
# Validate:   midi-remapper --validate actition.py
# List banks: midi-remapper --list-banks actition.py
#
# This file is a plain Python dict literal.
# No imports, no function calls -- just data.
# Chord keys use '+' notation: "CC1+CC2" instead of ("CC1", "CC2").
#
# Live reloading: midi-remapper watches this file for changes while
# running.  Edit and save; new mappings take effect within one second.
# The active bank is preserved across reloads.  Pass --no-reload to
# disable watching.

#{
#    "name": "actition",
#    "active_bank": "default",
#
#    # Override global timing defaults (optional).
#    # "long_press_ms":         300,
#    # "multi_press_window_ms": 300,
#    # "chord_window_ms":        80,
#
#    "banks": {
#
#        "default": {
#            # Chord -> switch to drums bank (fast chord: all CC)
#            "CC1+CC2": {
#                "single": [{"send": "BANK", "bank": "drums"}],
#                "double": [{"send": "BANK", "bank": "ardour"}],
#            },
#
#            # Direct CC remaps (both press and release forwarded)
#            "CC0": [{"send": "CC0", "press_only": True}],
#            "CC2": [{"send": "CC2", "press_only": True}],
#            "CC3": [{"send": "CC3", "press_only": True}],
#
#            # Gesture: single/double/triple + long press on CC1
#            "CC1": {
#                "single": [{"send": "CC1",  "value": 127}],
#                "double": [{"send": "CC11", "value": 127}],
#                "triple": [{"send": "CC22", "value": 127}],
#                "long":   [{"send": "PC88"}],
#                "long_ms": 300,
#            },
#        },
#
#        "drums": {
#            "CC1+CC2": {"single": [{"send": "BANK", "bank": "default"}]},
#            "CC2+CC3": {"single": [{"send": "BANK", "bank": "ardour"}]},
#
#            "CC0": [{"send": "CC4", "press_only": True}],
#            "CC1": [{"send": "CC5", "press_only": True}],
#            "CC2": [{"send": "CC6", "press_only": True}],
#            "CC3": [{"send": "CC7", "press_only": True}],
#        },
#
#        "ardour": {
#            "CC1+CC2": {"single": [{"send": "BANK", "bank": "default"}]},
#            "CC2+CC3": {"single": [{"send": "BANK", "bank": "drums"}]},
#
#            "CC0": [{"send": "PC4", "press_only": True}],
#            "CC1": [{"send": "PC5", "press_only": True}],
#            "CC2": [{"send": "PC6", "press_only": True}],
#            "CC3": [{"send": "PC7", "press_only": True}],
#        },
#    },
#}

[{
    "name": "actition",
    "active_bank": "drums",

    # Override global timing defaults (optional).
    # "long_press_ms":         300,
    # "multi_press_window_ms": 300,
    # "chord_window_ms":        80,

    "banks": {
        "sooperlooper": {

            #"CC1+CC2": { "single": [{"send": "BANK", "bank": "drums"}], },
            #"CC2+CC3": { "single": [{"send": "BANK", "bank": "ardour"}], },

            "CC1+CC2": {
                "single": [{"send": "BANK", "bank": "drums"}],
                #"double": [{"send": "BANK", "bank": "ardour"}],
            },

            "CC0": [{"send": "CC0", "press_only": True}],
            "CC1": [{"send": "CC1", "press_only": True}],
            "CC2": [{"send": "CC2", "press_only": True}],
            "CC3": [{"send": "CC3", "press_only": True}],

            #"CC1": { # NOTE: These are dicts and latest key overwrites!!!!
            #    "single":  [{"send": "CC1", "value": 127}],
            #    "double":  [{"send": "CC11", "value": 127}],
            #    "triple":  [{"send": "CC22", "value": 127}],
            #    "long":    [{"send": "PC88"}],
            #    "long_ms": 300,
            #},

        },

        "drums": {
            # Chord -> switch back to default
            # ("CC4", "CC5"): {
            #     "single": [{"send": "BANK", "bank": "default"}],
            # },

            "CC1+CC2": { "single": [{"send": "BANK", "bank": "sooperlooper"}], },
            #"CC2+CC3": { "single": [{"send": "BANK", "bank": "ardour"}], },

            "CC0": [{"send": "CC4", "press_only": True}],
            #"CC1": [{"send": "CC5", "press_only": True}],
            #"CC2": [{"send": "CC6", "press_only": True}],

            #"CC1": { "single": [{"send": "CC5", "value": 127}],
            #         "double": [{"send": "CC25", "value": 127}],
            #         "triple": [{"send": "CC105", "value": 127}], },
            #"CC2": { "single": [{"send": "CC6", "value": 127}],
            #         "double": [{"send": "CC26", "value": 127}],
            #         "triple": [{"send": "CC106", "value": 127}], },
            #
            # Hold-repeat -- fires repeatedly while held; quick release fires 'single'
            "CC1": {
                "single":           [{"send": "CC5", "value": 127}],
                "double":           [{"send": "CC44", "value": 127}],
                "repeat":           [{"send": "CC5", "value": 127}],
                "repeat_delay_ms":  400,   # ms before first repeat
                "repeat_ms":        70,   # ms between subsequent repeats
            },
            "CC2": {
                "single":           [{"send": "CC6", "value": 127}],
                "double":           [{"send": "CC45", "value": 127}],
                "repeat":           [{"send": "CC6", "value": 127}],
                "repeat_delay_ms":  400,   # ms before first repeat
                "repeat_ms":        70,   # ms between subsequent repeats
            },

            "CC3": [{"send": "CC7", "press_only": True}],
         },

        "ardour": {
            "CC2+CC3": { "single": [{"send": "BANK", "bank": "sooperlooper"}], },
            #"CC2+CC3": { "double": [{"send": "BANK", "bank": "drums"}], },
            #"CC1+CC2": { "single": [{"send": "BANK", "bank": "drums"}], },

            "CC0": [{"send": "PC4", "press_only": True}],
            "CC1": [{"send": "PC5", "press_only": True}],
            "CC2": [{"send": "PC6", "press_only": True}],
            "CC3": [{"send": "PC7", "press_only": True}],
        },
    },
},

# A BankSet with a single bank that never switches, useful for mappings
# that should always be active regardless of other BankSets' states.
{
    "name": "global",
    "active_bank": "default",

    # Override global timing defaults (optional).
    # "long_press_ms":         300,
    # "multi_press_window_ms": 300,
    # "chord_window_ms":        80,

    "banks": {
        "default": {
            # Entries here are checked before actition_banks on every event.
        },
    },
}]

