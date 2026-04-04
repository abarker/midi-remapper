midi-event-remapper
===================

A MIDI event remapper built on top of `mididings`_ and JACK.  It lets you
map incoming MIDI events (CC, PC, Note) to different outgoing events, with
support for chords, long press, double/triple press, toggles, and switchable
mapping banks -- all configured in a simple data file with no programming
required.

.. _mididings: https://dsacre.github.io/mididings/doc/

.. contents:: Contents
   :depth: 2
   :local:

Installation
------------

From PyPI::

    pip install midi-event-remapper

From GitHub::

    pip install git+https://github.com/abarker/midi-event-remapper.git

Dependencies: ``mididings``, ``JACK-Client``, a running JACK server
(via QjackCtl or ``jackd``).

Quick start
-----------

1. Start JACK (e.g. open QjackCtl and press Start).
2. Create a config file ``mycontroller.mer`` (see `Config files`_ below).
3. Run::

    midi-remapper mycontroller.mer

4. Connect your controller's JACK MIDI output to
   ``midi_event_remapper:in_0`` and ``midi_event_remapper:out_0`` to
   your target application, using QjackCtl's Graph or ``jack_connect``.

Command-line reference
----------------------

::

    midi-remapper [FILE ...] [OPTIONS]

**Positional arguments**

``FILE``
    One or more ``.mer`` config files (see below).  Each file defines one
    or more BankSets.  Files are checked in order -- the first BankSet
    that matches an incoming event handles it.  If no files are given,
    the built-in ``config.py`` settings are used.

**Options**

``--validate``, ``-V``
    Validate config files and exit without connecting to JACK.  Use this
    to check a new config before a live session.

``--list-banks``, ``-l``
    Print the banks defined in each BankSet and exit.

``--bank BANKSET:BANK``, ``-b BANKSET:BANK``
    Override the starting bank for a named BankSet.  May be repeated::

        midi-remapper mycontroller.mer --bank actition:drums

``--debug`` / ``--no-debug``
    Enable or disable debug output (overrides the file setting).

``--long-press-ms MS``
    Override the long-press threshold for this session.

``--multi-press-ms MS``
    Override the multi-press accumulation window.

``--chord-ms MS``
    Override the chord detection window.

Config files
------------

A ``.mer`` file is a plain Python data literal -- no imports, no function
calls, just a dict (single BankSet) or list of dicts (multiple BankSets).
Comments use ``#``.  Chord keys use ``+`` notation::

    # mycontroller.mer
    {
        "name": "mycontroller",
        "active_bank": "default",

        "banks": {
            "default": {
                # Direct remap: CC0 -> CC10 (press and release forwarded)
                "CC0": [{"send": "CC10"}],

                # Press only
                "CC1": [{"send": "CC11", "press_only": True}],

                # Gesture: long press + double tap on CC2
                "CC2": {
                    "single": [{"send": "CC12", "value": 127}],
                    "double": [{"send": "CC22", "value": 127}],
                    "long":   [{"send": "PC5"}],
                    "long_ms": 300,
                },

                # Chord: switch banks when CC3 and CC4 are pressed together
                "CC3+CC4": {
                    "single": [{"send": "BANK", "bank": "layer2"}],
                },
            },

            "layer2": {
                "CC3+CC4": {"single": [{"send": "BANK", "bank": "default"}]},
                "CC0": [{"send": "CC20", "press_only": True}],
                "CC1": [{"send": "CC21", "press_only": True}],
            },
        },
    }

A single file can hold multiple BankSets as a list::

    [
        {
            "name": "global",
            "banks": {
                "default": {
                    # Always-active mappings checked before any other BankSet
                },
            },
        },
        {
            "name": "mycontroller",
            ...
        },
    ]

Validate before running::

    midi-remapper --validate mycontroller.mer

List available banks::

    midi-remapper --list-banks mycontroller.mer

Mapping types
-------------

**Direct**

Maps an event immediately on press and release.  The incoming value is
forwarded by default; use ``"value"`` to fix it or ``"press_only"`` to
suppress the release::

    "CC0": [{"send": "CC10"}],                        # both press and release
    "CC0": [{"send": "CC10", "press_only": True}],    # press only
    "CC0": [{"send": "CC10", "value": 127}],          # always sends 127

Multiple outputs per event::

    "PC5": [
        {"send": "NOTE36", "velocity": 127},
        {"send": "CC10",   "value": 64},
    ],

**Toggle**

Alternates between two sequences on each press::

    "CC5": {
        "a": [{"send": "CC40", "value": 127}],
        "b": [{"send": "CC40", "value": 0}],
    },

**Gesture** (single / double / triple / long)

Any combination of press counts and long hold.  Only the labels you
define are active -- the rest are ignored::

    # Single only -- fires immediately, zero latency
    "CC0": {"single": [{"send": "CC10", "value": 127}]},

    # Long press -- fires at threshold, no release needed
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "long":   [{"send": "PC5"}],
        "long_ms": 400,
    },

    # Multi-press -- incurs MULTI_PRESS_WINDOW_MS delay (default 300ms)
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "double": [{"send": "CC20", "value": 127}],
        "triple": [{"send": "CC30", "value": 127}],
    },

    # Combined -- long fires at threshold; multi window starts after quick release
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "double": [{"send": "CC20", "value": 127}],
        "long":   [{"send": "PC5"}],
        "long_ms": 300,
    },

``"long"`` requires a momentary input (CC or NOTE) -- not valid for PC
keys.  Works with NOTE keys too::

    "NOTE60": {
        "single": [{"send": "CC10", "value": 127}],
        "long":   [{"send": "CC11", "value": 127}],
    },

**Chord**

Fires when all keys in the tuple arrive within ``CHORD_WINDOW_MS``
(default 80ms)::

    "CC1+CC2": {
        "single": [{"send": "BANK", "bank": "drums"}],
        "double": [{"send": "BANK", "bank": "ardour"}],
    },

All-CC or all-NOTE chords are **fast chords**: if only one key arrives
and is then released, the window cancels immediately and the individual
key mapping fires with near-zero latency.  Mixed PC/CC chords always wait
the full window.

.. important::

   All labels for the same chord key must be in a single dict entry.
   Python silently discards duplicate keys, so two separate entries for
   ``"CC1+CC2"`` will lose the first one.  Always write::

       "CC1+CC2": {
           "single": [...],
           "double": [...],
       },

**Bank switching**

Use the special ``"BANK"`` send to switch to another bank::

    "CC3+CC4": {
        "single": [{"send": "BANK", "bank": "layer2"}],
    },

Bank switches can be combined with other sends in the same sequence::

    "CC3+CC4": {
        "single": [
            {"send": "CC0", "value": 0},
            {"send": "BANK", "bank": "layer2"},
        ],
    },

Latency summary
---------------

+-----------------------------------+------------------------------+
| Feature                           | When output fires            |
+===================================+==============================+
| Direct                            | Immediately on press (~0ms)  |
+-----------------------------------+------------------------------+
| Gesture single only               | Immediately on press (~0ms)  |
+-----------------------------------+------------------------------+
| Toggle                            | Immediately on press (~0ms)  |
+-----------------------------------+------------------------------+
| Chord (complete)                  | When last key arrives (~0ms) |
+-----------------------------------+------------------------------+
| Fast chord fallback               | On key release (~0ms)        |
+-----------------------------------+------------------------------+
| Standard chord fallback           | After CHORD_WINDOW_MS (80ms) |
+-----------------------------------+------------------------------+
| Gesture multi-press               | After MULTI_PRESS_WINDOW_MS  |
|                                   | (300ms default)              |
+-----------------------------------+------------------------------+
| Gesture long                      | At long_ms threshold         |
+-----------------------------------+------------------------------+
| Gesture single + long (single)    | On quick release             |
+-----------------------------------+------------------------------+

Sequence item reference
-----------------------

Each output in a sequence is a dict with the following keys:

``"send"`` *(required)*
    The event to send: ``"CC<n>"``, ``"PC<n>"``, or ``"NOTE<n>"``.
    Special value ``"BANK"`` switches banks (also requires ``"bank"``).

``"value"``
    CC value 0--127.  If omitted, the incoming event value is forwarded.

``"velocity"``
    Note velocity 0--127 (default 127).  For NOTE sends only.

``"note_off"``
    If ``True``, send a NoteOff instead of NoteOn (default ``False``).

``"press_only"``
    If ``True``, skip this item on release events.  Only meaningful for
    direct mappings.

``"delay"``
    Seconds to wait before sending (default 0.0).

``"bank"``
    Target bank name.  Required when ``"send"`` is ``"BANK"``.

.. note::

    Using ``"velocity"`` on a CC send or ``"value"`` on a NOTE send is a
    config error caught by ``--validate`` at startup.

Trigger value filtering
-----------------------

Add ``"trigger_value"`` to a gesture or direct entry to only dispatch
when the incoming value matches::

    "CC0": {
        "trigger_value": "64-127",
        "single": [{"send": "CC10", "value": 127}],
    },

Supported forms::

    "trigger_value": 127            # exact
    "trigger_value": "64-127"       # inclusive range
    "trigger_value": ">64"          # greater than
    "trigger_value": "<=64"         # less than or equal
    "trigger_value": [1, "64-127"]  # OR list (avoid 0 for CC keys)

Timing constants
----------------

These can be overridden per-file or on the command line:

``long_press_ms`` (default 500)
    Threshold for the ``"long"`` gesture action.

``multi_press_window_ms`` (default 300)
    Accumulation window for double/triple press.

``chord_window_ms`` (default 80)
    Window within which all chord keys must arrive.

``debounce_ms`` (default 60)
    Minimum time between toggle triggers.

JACK connection
---------------

After starting ``midi-remapper``, connect ports in QjackCtl Graph or
with ``jack_connect``::

    jack_connect \
        "a2j:MyController [20] (capture): MyController MIDI 1" \
        "midi_event_remapper:in_0"

    jack_connect \
        "midi_event_remapper:out_0" \
        "Hydrogen-midi:RX"

The client name ``midi_event_remapper`` can be changed via
``CLIENT_NAME`` in ``config.py``.

Development
-----------

Clone and install in editable mode::

    git clone https://github.com/abarker/midi-event-remapper.git
    cd midi-event-remapper
    pip install -e ".[dev]"
    pytest

License
-------

MIT
