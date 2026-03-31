#!/usr/bin/env python3
"""
run_midi_remapper.py

Entry point.  Make sure JACK is running before executing this script.

Install the package first:
    pip install -e /path/to/mididings_event_remapper

Then run:
    python bin/run_midi_remapper.py

Or connect JACK ports after starting:
    jack_connect \\
        "a2j:UMC404HD 192k [20] (capture): [0] UMC404HD 192k MIDI 1" \\
        "mididings_event_remapper:in_0"
    jack_connect \\
        "mididings_event_remapper:out_0" \\
        "Hydrogen-midi:RX"
"""
from midi_event_remapper.dispatcher import run

if __name__ == "__main__":
    run()

