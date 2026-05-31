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

The package is not on PyPI.  Clone the repository first::

    git clone https://github.com/abarker/midi-event-remapper.git
    cd midi-event-remapper

Then choose one of the four install options below.

**Install options**

There are two axes: *regular* vs *editable* (developer) install, and
*pure Python* vs *with the optional Cython RT extension*.

Regular install
    The package is copied into the active Python environment.  Source
    changes are not reflected until you reinstall.

Editable install (``--dev``)
    The package is linked to the source tree so changes take effect
    immediately.  Also installs pytest and other dev dependencies.

Cython RT extension (``--cython``)
    Builds ``midi_core``, which accelerates the MIDI event hot path.
    Optional and off by default.  Worth trying only if you use
    ``--jack-rt`` and still see occasional xruns.  Re-run the
    install command after editing ``midi_core.pyx`` to recompile.

**Using the install script (easier)**

``bin/install.sh`` handles all four combinations.  Run it with no
arguments for an interactive menu::

    bash bin/install.sh

Or pass flags for non-interactive use::

    bash bin/install.sh                      # regular, pure Python
    bash bin/install.sh --cython             # regular, with Cython
    bash bin/install.sh --dev                # editable, pure Python
    bash bin/install.sh --dev --cython       # editable, with Cython

Add ``--no-tests`` to skip the post-install test run.

**Manual pip commands**

Regular install::

    pip install .                            # pure Python
    pip install ".[rt]"                     # with Cython extension

Editable install::

    pip install -e ".[dev]"                 # pure Python

    pip install -e ".[dev,rt]"              # with Cython extension
    python setup.py build_ext --inplace      # (also run this step)

The ``[rt]`` extra installs Cython; ``[dev]`` adds pytest.  Re-run
``python setup.py build_ext --inplace`` after editing ``midi_core.pyx``.

**Dependencies**

``mididings``, ``JACK-Client``, ``python-osc``, and a running JACK
server (via QjackCtl or ``jackd``).

Quick start
-----------

1. Start JACK (e.g. open QjackCtl and press Start).
2. Create a config file ``mycontroller.py`` (see `Config files`_ below).
3. Run::

    midi-remapper mycontroller.py

4. Connect your controller's JACK MIDI output to
   ``midi_remapper:in_0`` and ``midi_remapper:out_0`` to
   your target application, using QjackCtl's Graph or ``jack_connect``.

Command-line reference
----------------------

::

    midi-remapper FILE [FILE ...] [OPTIONS]

**Positional arguments**

``FILE`` (required)
    One or more ``.py`` config files (see below).  Each file defines one
    or more BankSets.  Files are checked in order -- the first BankSet
    that matches an incoming event handles it.  Files are watched for
    changes and reloaded automatically while the program runs (see
    `Live reloading`_).

**Options**

``--display``, ``-d``
    Open a floating window that shows the current bank name in large text.
    The window stays on top of other windows and updates instantly on every
    bank switch.  Useful during live performance to confirm that a chord or
    double-press registered.  Requires ``tkinter`` (standard library on most
    systems; install ``python3-tk`` on Debian/Ubuntu if missing).

``--no-titlebar``
    Same as ``--display``, but removes the OS title bar so the window takes
    up less screen space.  Right-click anywhere on the window to show a menu
    with **Exit** (quit the program) and **Cancel** (dismiss the menu).

``--validate``, ``-V``
    Validate config files and exit without connecting to JACK.  Use this
    to check a new config before a live session.

``--list-banks``, ``-l``
    Print the banks defined in each BankSet and exit.

``--bank BANKSET:BANK``, ``-b BANKSET:BANK``
    Override the starting bank for a named BankSet.  May be repeated::

        midi-remapper mycontroller.py --bank actition:drums

``--debug`` / ``--no-debug``
    Enable or disable all debug output.  Sets both the dispatcher-level
    flag (``[in]`` / ``[dispatch]`` lines) and the per-BankSet internal
    trace simultaneously.  Overrides any ``"debug"`` setting in the
    config file.  See `Debug output`_ for details.

``--long-press-ms MS``
    Override the long-press threshold for this session.

``--multi-press-ms MS``
    Override the multi-press accumulation window (global default).
    Individual keys can override this further with ``"multi_ms"`` in
    their entry dict.

``--chord-ms MS``
    Override the chord detection window.

``--no-reload``
    Disable live config file reloading.  By default, any config files
    passed on the command line are watched for changes and reloaded
    automatically while the program runs (see `Live reloading`_ below).

``--jack-rt``
    Use the mididings ``jack-rt`` backend instead of the default ``jack``
    backend.  In ``jack-rt`` mode the MIDI handler runs directly inside
    the JACK process callback rather than in a separate thread.

    **Latency benefit for synchronous events**

    The ``jack`` buffered backend always adds one full JACK period of
    latency because events are queued and processed in the *next* callback
    cycle.  With ``jack-rt``, events that can be handled without waiting
    (see below) are written to the JACK output buffer in the *same*
    callback cycle -- one period (e.g. ~10.7 ms at 512 samples / 48 kHz)
    earlier.

    The following remapper features are **synchronous** and benefit from
    this reduced latency:

    - Direct mappings (``"CC0": [{"send": "CC4"}]``) -- both press and
      release
    - Toggle entries
    - Gesture entries where **only** ``"single"`` is defined (no
      ``"double"``, ``"triple"``, ``"long"``, or ``"repeat"``)
    - Chord completions -- when all chord keys arrive within the window

    The following features are **not synchronous** and fire via timer
    callbacks regardless of backend, so they see no timing benefit:

    - Any gesture entry that includes ``"double"``, ``"triple"``,
      ``"long"``, or ``"repeat"`` (even the ``"single"`` branch of such
      an entry waits for the multipress window)
    - Chord fallback (when the chord does not complete in time)
    - Chord multipress (``"double"`` / ``"triple"`` chord completions)
    - Delayed sends (``"delay": ...``)

    **SooperLooper timestamp precision**

    ``jack-rt`` also preserves JACK MIDI intra-block timestamps
    end-to-end.  A planned SooperLooper patch (``TriggerLatency =
    buffersize - intra_block_offset``) would exploit these timestamps to
    achieve exact loop-boundary alignment for synchronous events -- zero
    net error regardless of where within the block the button was pressed.
    This benefit requires both ``--jack-rt`` *and* the SooperLooper patch;
    neither alone is sufficient.  Without the patch, ``--jack-rt`` does
    not improve loop-boundary precision.

    Also calls ``sys.setswitchinterval(0.0001)`` to reduce the chance
    that the Python GIL is held by another thread when the JACK callback
    fires, and runs ``gc.collect()`` + ``gc.freeze()`` after startup so
    the cyclic garbage collector never scans startup objects.  Runtime
    objects (created after startup completes) are still collected normally.

    **WARNING:** Python code in the JACK RT callback is not real-time
    safe.  A slow or blocking handler (GUI update, file I/O, logging)
    can cause xruns in *all* JACK clients, not just this program.  The
    bank display window runs in a separate process with its own GIL, so
    it cannot contend with the RT callback.  Updates from the RT callback
    to the display are a bare ``deque.append()`` (no mutex, no cross-process
    call), and a background relay thread forwards them to the display process
    over a pipe.  With a lean handler and a reasonable buffer size (e.g. 512
    samples) this mode is often workable in practice.  If no xruns are
    observed it is worth using.

Config files
------------

A ``.py`` file is a plain Python data literal -- no imports, no function
calls, just a dict (single BankSet) or list of dicts (multiple BankSets).
Comments use ``#``.  Chord keys use ``+`` notation::

    # mycontroller.py
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
                "_display": {"bg": "#2e1a1a", "fg": "#ffb0a0"},
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

    midi-remapper --validate mycontroller.py

List available banks::

    midi-remapper --list-banks mycontroller.py

**Key name case**

Event key names are case-insensitive: ``"cc5"`` is equivalent to
``"CC5"``, and ``"note60"`` to ``"NOTE60"``.  Chord components are
normalised individually, so ``"cc1+cc2"`` is the same as ``"CC1+CC2"``.
Uppercase is conventional in examples and documentation.

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

    # Multi-press with per-key window override
    "CC0": {
        "single":   [{"send": "CC10", "value": 127}],
        "double":   [{"send": "CC20", "value": 127}],
        "multi_ms": 150,   # tighter window for this key only
    },

    # Combined -- long fires at threshold; multi window starts after quick release
    "CC0": {
        "single": [{"send": "CC10", "value": 127}],
        "double": [{"send": "CC20", "value": 127}],
        "long":   [{"send": "PC5"}],
        "long_ms": 300,
    },

    # Hold-repeat -- fires repeatedly while held; quick release fires 'single'
    "CC0": {
        "single":           [{"send": "CC10", "value": 127}],
        "repeat":           [{"send": "CC10", "value": 127}],
        "repeat_delay_ms":  400,   # ms before first repeat
        "repeat_ms":        120,   # ms between subsequent repeats
    },

    # Repeat-only -- no action on quick tap
    "CC0": {
        "repeat":           [{"send": "CC10", "value": 127}],
        "repeat_delay_ms":  300,
        "repeat_ms":        100,
    },

    # Accelerating repeat -- different sequence and/or interval per tier.
    # Each tier activates when the key has been held for after_ms or more.
    # Omit "repeat" in a tier to keep the current sequence and change
    # only the interval; omit "repeat_ms" to keep the current interval.
    "CC0": {
        "single":          [{"send": "CC10", "value": 127}],
        "repeat":          [{"send": "CC10", "value": 1}],
        "repeat_delay_ms": 400,
        "repeat_ms":       150,
        "repeat_accel": [
            # After 1.5s held: step by 2, same 150ms interval.
            {"after_ms": 1500,
             "repeat": [{"send": "CC10", "value": 2}]},
            # After 3s held: step by 5, faster 80ms interval.
            {"after_ms": 3000,
             "repeat": [{"send": "CC10", "value": 5}],
             "repeat_ms": 80},
        ],
    },

    # Interval-only acceleration: same sequence but faster over time.
    "CC0": {
        "repeat":          [{"send": "CC10", "value": 1}],
        "repeat_delay_ms": 400,
        "repeat_ms":       200,
        "repeat_accel": [
            {"after_ms": 1500, "repeat_ms": 100},
            {"after_ms": 3000, "repeat_ms":  50},
        ],
    },

``"long"`` and ``"repeat"`` both require a momentary input (CC or NOTE) --
not valid for PC keys.  They are mutually exclusive.  Works with NOTE
keys too::

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

Shell commands
--------------

Use ``"CMD"`` to run an arbitrary shell command when an event fires.
The command runs in a background thread and does not block the MIDI
handler.  stdout and stderr are printed when ``--debug`` is active::

    # Single command
    "CC3": [{"send": "CMD", "cmd": "jack_transport start"}],

    # Combined with MIDI output
    "CC3": [
        {"send": "CC10", "value": 127},
        {"send": "CMD",  "cmd": "jack_transport start"},
    ],

    # On a long press
    "CC3": {
        "single": [{"send": "CMD", "cmd": "jack_transport stop"}],
        "long":   [{"send": "CMD", "cmd": "jack_transport locate 0"}],
    },

    # Chord that switches bank AND runs a command
    "CC3+CC4": {
        "single": [
            {"send": "BANK", "bank": "drums"},
            {"send": "CMD",  "cmd": "echo drums > /tmp/current_bank.txt"},
        ],
    },

Commands run via the shell (``shell=True``), so pipes, redirects, and
environment variables all work.  Some useful examples::

    jack_transport start
    jack_transport stop
    jack_transport locate 0   # prefer JACK_TRANSPORT for this -- see below
    aconnect 14:0 128:0
    echo 120 > /tmp/bpm.txt
    notify-send "Bank: drums"

JACK transport control
----------------------

Use ``JACK_TRANSPORT`` to control JACK transport (play, stop, locate)
without spawning a subprocess.  A persistent JACK client
(``midi_remapper_ctrl``) is opened once when a ``JACK_TRANSPORT`` action
is detected in a config file during loading; all subsequent actions reuse
the same connection.  Because no ``fork``/``exec`` occurs and no new JACK
client is registered at action time, recording clients are not disturbed.
Prefer this over ``CMD`` with ``jack_transport`` when other clients are
recording::

    # Rewind to the start of the timeline.
    "CC6": [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],

    # Start and stop rolling.
    "CC7": [{"send": "JACK_TRANSPORT", "transport": "start"}],
    "CC8": [{"send": "JACK_TRANSPORT", "transport": "stop"}],

    # Stop and rewind on a gesture.
    "CC6": {
        "single": [{"send": "JACK_TRANSPORT", "transport": "stop"}],
        "long":   [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
    },

    # Combined with a MIDI output in the same sequence.
    "CC6": [
        {"send": "CC60", "value": 127},
        {"send": "JACK_TRANSPORT", "transport": "locate 0"},
    ],

Valid ``"transport"`` values:

``"locate <frame>"``
    Reposition to *frame* samples from time zero.  ``0`` rewinds to the
    beginning.  At 48 kHz, frame 48000 = 1 second.

``"start"``
    Begin rolling.

``"stop"``
    Stop rolling.

The ``"delay"`` key is supported, same as for ``CMD``.

The ``midi_remapper_ctrl`` client is portless and appears as a passive
entry in the JACK client list.  No port connections are needed.

OSC sends
---------

Use ``"OSC"`` to send an OSC message over UDP when an event fires.

One ``SimpleUDPClient`` is created per ``(host, port)`` target when the
config is loaded and reused for every subsequent send -- no new socket is
opened at action time::

    # Simple no-argument message.
    "CC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/ping"}],

    # With typed arguments: int, float, and str are all valid.
    "CC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/record/arm", "args": [1]}],

    "CC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/fader/level", "args": [0.75]}],

    "CC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/scene/load", "args": ["verse"]}],

    # Multiple arguments in one message.
    "CC5": [{"send": "OSC", "host": "10.0.0.5", "port": 7400,
             "address": "/channel/set", "args": [1, 0.8, "armed"]}],

    # Multiple targets in one sequence.
    "CC5": [
        {"send": "OSC", "host": "127.0.0.1", "port": 9000,
         "address": "/local/trigger"},
        {"send": "OSC", "host": "10.0.0.5",  "port": 7400,
         "address": "/remote/trigger"},
    ],

    # Combined with a MIDI output and delayed.
    "CC5": [
        {"send": "CC50", "value": 127},
        {"send": "OSC",  "host": "127.0.0.1", "port": 9000,
         "address": "/cue/fire", "delay": 0.1},
    ],

    # On a gesture.
    "CC5": {
        "single": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                    "address": "/transport/stop"}],
        "long":   [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                    "address": "/transport/locate", "args": [0]}],
    },

Required keys: ``"host"``, ``"port"``, ``"address"``.

``"address"`` must be a string starting with ``/``.

``"args"`` is optional (default: no-argument message).  Each element
must be ``int``, ``float``, or ``str``; booleans are not accepted.

``"delay"`` is supported, as for ``CMD`` and ``JACK_TRANSPORT``.

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
| Gesture repeat (first)            | After repeat_delay_ms (500ms)|
+-----------------------------------+------------------------------+
| Gesture repeat (subsequent)       | Every repeat_ms (100ms)      |
+-----------------------------------+------------------------------+
| Gesture single + repeat (single)  | On quick release if no       |
|                                   | repeat has fired yet         |
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

``"channel"``
    MIDI channel for the outgoing event (integer, 1--16 with the default
    ``data_offset=1``).  If omitted the incoming event's channel is
    passed through unchanged.  Useful when a single controller button
    must drive events on multiple channels, or when the output channel
    should differ from whatever channel the controller sends on::

        # Send CC10 on channel 2 regardless of the incoming channel
        "CC5": [{"send": "CC10", "value": 127, "channel": 2}],

        # Sequence that fans out to two channels
        "CC6": [
            {"send": "NOTE60", "velocity": 127, "channel": 1},
            {"send": "NOTE60", "velocity": 127, "channel": 2},
        ],

    The valid range is ``data_offset`` to ``15 + data_offset`` (same
    convention as channel fields elsewhere in the config).  Out-of-range
    values are caught by ``--validate`` at startup.

``"bank"``
    Target bank name.  Required when ``"send"`` is ``"BANK"``.

``"cmd"``
    Shell command string.  Required when ``"send"`` is ``"CMD"``.

``"transport"``
    JACK transport command string.  Required when ``"send"`` is
    ``"JACK_TRANSPORT"``.  Valid values: ``"locate <frame>"``,
    ``"start"``, ``"stop"``.

``"host"``
    Destination hostname or IP address.  Required when ``"send"`` is
    ``"OSC"``.

``"port"``
    Destination UDP port (integer 1--65535).  Required when ``"send"``
    is ``"OSC"``.

``"address"``
    OSC address string (must start with ``/``).  Required when
    ``"send"`` is ``"OSC"``.

``"args"``
    List of OSC arguments (optional, default: empty / no-argument
    message).  Each element must be ``int``, ``float``, or ``str``.

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
    Override per-key with ``"long_ms"`` in the entry dict.

``multi_press_window_ms`` (default 300)
    Accumulation window for double/triple press (gesture and chord).
    Override per-key with ``"multi_ms"`` in the entry dict::

        "CC0": {
            "single": [{"send": "CC10", "value": 127}],
            "double": [{"send": "CC20", "value": 127}],
            "multi_ms": 150,   # tighter window just for this key
        },

``chord_window_ms`` (default 80)
    Window within which all chord keys must arrive.

``debounce_ms`` (default 60)
    Minimum time between toggle triggers.

``repeat_delay_ms`` (default 500)
    Hold time before the first repeat fires.
    Override per-key with ``"repeat_delay_ms"`` in the entry dict.

``repeat_ms`` (default 100)
    Interval between subsequent repeat firings.
    Override per-key with ``"repeat_ms"`` in the entry dict.

``repeat_accel``
    Optional list of acceleration tiers for ``"repeat"`` gestures.
    Not a global constant -- specified per entry only.
    See `Gesture mappings`_ for the full tier syntax.

Bank display window
-------------------

Run with ``--display`` to open a floating window showing the current bank
name in a large, easy-to-read font::

    midi-remapper mycontroller.py --display

Add ``--no-titlebar`` to remove the OS title bar for a more compact display::

    midi-remapper mycontroller.py --no-titlebar

In titlebar-less mode, right-click anywhere on the window for a menu with
**Exit** (quit the program) and **Cancel** (dismiss the menu).

The window stays on top of other windows and updates immediately on every
bank switch, so you can glance at it during a performance to confirm that
a chord or double-press registered correctly.

**Per-bank styling**

Each bank can define its own background colour, text colour, font size,
and window dimensions via a ``"_display"`` key placed directly inside the
bank dict in the config file::

    "banks": {
        "default": {
            "_display": {"bg": "#1a1a2e", "fg": "#e0e0ff"},
            "CC0": [{"send": "CC10", "press_only": True}],
        },
        "drums": {
            "_display": {"bg": "#1a2e1a", "fg": "#a0ffb0",
                         "font_size": 80, "width": 400, "height": 200},
            "CC0": [{"send": "CC11", "press_only": True}],
        },
    },

All five keys are optional.  Any key omitted falls back to the defaults
in ``bank_display.py`` (dark background, white text, 72-point font).
``"_display"`` is stripped before MIDI mapping lookup and does not
interfere with any event key.

Style changes take effect immediately on the next bank switch.  When the
config file is reloaded live, the new styles are applied at once without
needing to switch banks first.

Available style keys:

==================  ===========================================
Key                 Effect
==================  ===========================================
``bg``              Background colour (any Tk colour string)
``fg``              Text colour
``font_size``       Bank-name font size in points
``width``           Window width in pixels
``height``          Window height in pixels
==================  ===========================================

Debug output
------------

Two independent debug flags control what is printed:

``config.DEBUG`` (dispatcher level)
    Prints ``[in]`` (every incoming event), ``[dispatch]`` (which BankSet
    handled it), and startup messages.  Set to ``True`` in ``config.py``,
    use ``--debug`` on the command line, or add ``"debug": True`` to the
    global settings block of a config file (this last option is
    hot-reloadable).

``BankSet._debug`` (BankSet level)
    Prints ``[BankSet:name] handle key=...``, gesture timing, chord
    windows, and sequence dispatch detail for that specific BankSet.
    Set per-BankSet via ``"debug": True`` inside a BankSet dict.

The ``--debug`` CLI flag sets both levels simultaneously and is the
simplest way to get full output.  Setting ``"debug": True`` inside a
BankSet dict gives internal trace for that BankSet only, without the
dispatcher-level wrapper lines.  This is useful when you have multiple
BankSets and want to trace only one without flooding the terminal.

Live reloading
--------------

When one or more config files are passed on the command line,
``midi-remapper`` watches them for changes and reloads them automatically
while the program is running.  This makes it easy to experiment with
mappings without restarting:

1. Start ``midi-remapper`` as usual::

       midi-remapper mycontroller.py

2. Edit and save ``mycontroller.py`` in your text editor.
3. The program detects the change within about one second and prints::

       [reload] mycontroller.py changed, reloading...
       [reload] mycontroller.py: OK  (active banks: mycontroller=default)

   Your new mappings take effect immediately.

If the file contains a syntax or validation error, the current config is
kept and an error message is printed -- the program keeps running on the
last good config.  Fix the error and save again to retry.

The currently active bank is preserved across reloads when the bank name
still exists in the new config.  If you rename or remove the active bank,
the BankSet resets to its ``active_bank`` setting (usually ``"default"``).

Pass ``--no-reload`` to disable file watching entirely.

The ``"debug"`` key in a global settings block is one of the things that
can be toggled live::

    [
        {"debug": True},
        {"name": "main", "banks": { ... }},
    ]

Changing ``"debug"`` from ``False`` to ``True`` and saving will enable
dispatcher-level output immediately without restarting.

JACK connection
---------------

After starting ``midi-remapper``, connect ports in QjackCtl Graph or
with ``jack_connect``::

    jack_connect \
        "a2j:MyController [20] (capture): MyController MIDI 1" \
        "midi_remapper:in_0"

    jack_connect \
        "midi_remapper:out_0" \
        "Hydrogen-midi:RX"

The client name ``midi_remapper`` can be changed with ``--client-name NAME``
on the command line, or permanently via ``CLIENT_NAME`` in ``config.py``.

Development
-----------

Clone and install in editable mode::

    git clone https://github.com/abarker/midi-event-remapper.git
    cd midi-event-remapper
    pip install -e ".[dev]"
    pytest

Optional Cython extension
~~~~~~~~~~~~~~~~~~~~~~~~~

An optional Cython extension (``midi_event_remapper.midi_core``) replaces
the pure-Python ``event_key()``, ``is_release()``, and ``build_event()``
functions in ``midi.py`` with C-typed equivalents.  The pure-Python
fallback is always available and used automatically when the extension is
not present.

**Most users do not need this.**  The extension is worth trying only if
you are using ``--jack-rt`` and still seeing occasional xruns after the
other mitigations (``gc.freeze``, reduced switch interval, display
subprocess) have been applied.  The improvement is modest.

When ``--jack-rt`` is active, the startup message reports which
implementation is in use.

To build, use the install script::

    bash bin/install.sh --cython        # regular install
    bash bin/install.sh --dev --cython  # editable install

Or manually::

    pip install ".[rt]"                    # installs Cython
    python setup.py build_ext --inplace    # compiles midi_core.pyx

Re-run either command after editing ``midi_core.pyx``.

To verify::

    python -c "from midi_event_remapper.midi import _CYTHON_CORE; print(_CYTHON_CORE)"

This prints ``True`` if the extension is active.

**Forcing the pure Python fallback**

Once built the extension is used automatically.  To run without it
-- for debugging or to test the fallback path -- set
``MIDI_REMAPPER_NO_CYTHON=1``::

    MIDI_REMAPPER_NO_CYTHON=1 midi-remapper myconfig.py

The same variable controls which path the test suite exercises::

    pytest                              # tests whichever is installed
    MIDI_REMAPPER_NO_CYTHON=1 pytest    # forces pure Python fallback

Running both is the only way to confirm both implementations are correct.
The flag must be an environment variable rather than a command-line switch
because the choice is made at module import time, before argument parsing.

Phase 1 (current) uses C-typed local variables to reduce Python attribute
lookup overhead on every event.  Phase 2 (future) will add ``nogil``
sections for the scalar classification logic.

License
-------

MIT
