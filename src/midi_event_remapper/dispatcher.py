"""
dispatcher.py

Mididings setup and event dispatch loop.  This is the only module in the
package that imports mididings directly; it is never imported by the test
suite.
"""
from mididings import config as mididings_config, run as mididings_run, \
    Process, Output
import mididings.engine as engine

from midi_event_remapper import config
from midi_event_remapper.midi import event_key


def setup():
    """Configure mididings and wire output_fn into all BankSets."""
    mididings_config(
        backend     = config.BACKEND,
        client_name = config.CLIENT_NAME,
        in_ports    = [config.IN_PORT],
        out_ports   = [config.OUT_PORT],
        data_offset = config.DATA_OFFSET,
    )
    for bs in config.BANK_SETS:
        bs.set_output_fn(engine.output_event)


def main_handler(event):
    """
    Main mididings event handler.  Offers each incoming event to the
    BankSets in config.BANK_SETS in order.  The first BankSet that
    returns a non-None result handles the event; remaining BankSets are
    skipped.  If no BankSet matches, the event is passed through
    unchanged.
    """
    if config.DEBUG:
        print(f"[in] channel={event.channel} type={event.type} {event}")

    for bankset in config.BANK_SETS:
        result = bankset.handle(event)
        if result is not None:
            if config.DEBUG:
                print(
                    f"  [dispatch] handled by BankSet {bankset.name!r}"
                )
            return result

    return event   # pass through unchanged


def run():
    """Validate config, set up mididings, and start the event loop."""
    if config.DEBUG:
        print("\nStarting midi_event_remapper.\n")

    all_errors = []
    for bs in config.BANK_SETS:
        all_errors.extend(bs.validate())
    if all_errors:
        print("\n[startup] CONFIG ERRORS:")
        for e in all_errors:
            print(f"  x {e}")
        raise SystemExit("Fix config errors before running.")
    elif config.DEBUG:
        print("[startup] All BankSets validated OK.\n")

    setup()

    mididings_run(
        Process(main_handler) >>
        Output(port=config.PORT_INDEX, channel=config.CHANNEL)
    )

    print("\nExiting midi_event_remapper.")
