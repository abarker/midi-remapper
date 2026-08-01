"""
dispatcher.py

Mididings setup and event dispatch loop.  This is the only module in the
package that imports mididings directly; it is never imported by the test
suite.
"""
import subprocess
import sys
import time

from mididings import config as mididings_config, run as mididings_run, \
    Process, Output
import mididings.engine as engine

from midi_event_remapper import config
from midi_event_remapper.midi import event_key


def check_jack():
    """
    Verify that JACK is running before attempting to start mididings.

    Uses jack_wait if available (cleanest check), otherwise falls back to
    scanning the process list for jackd or pipewire-jack.  Exits with a
    clear message if JACK is not found.
    """
    # Try jack_wait first -- it is purpose-built for this check.
    try:
        result = subprocess.run(
            ["jack_wait", "-c", "-t", "1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return  # JACK is running
        print(
            "\n[startup] ERROR: JACK does not appear to be running.\n"
            "  Start JACK (via QjackCtl or 'jackd') before running this script.\n"
        )
        sys.exit(1)
    except FileNotFoundError:
        pass  # jack_wait not installed; fall through to process check

    # Fallback: check for jackd or pipewire process names.
    try:
        out = subprocess.check_output(
            ["pgrep", "-x", "-l", "jackd,jackdbus,pipewire"],
            stderr=subprocess.DEVNULL,
        ).decode()
        if out.strip():
            return  # found a matching process
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Also accept pipewire-jack via pactl/pw-cli presence.
    try:
        out = subprocess.check_output(
            ["pw-cli", "info", "all"],
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).decode()
        if "jack" in out.lower():
            return
    except Exception:
        pass

    print(
        "\n[startup] WARNING: Could not confirm JACK is running.\n"
        "  If you see connection errors, start JACK before running this script.\n"
        "  (Install jack_wait for a reliable check: 'apt install jackd2')\n"
    )
    # Warning only -- do not exit, in case the check is a false negative.


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

    Exceptions are caught and printed rather than propagated into the
    mididings event loop, where the behaviour on an unhandled exception
    is undefined and could silently stop all MIDI output.

    Debug output at this level is gated on ``config.DEBUG`` (the global
    dispatcher flag), set via ``DEBUG`` in ``config.py``, ``--debug`` on
    the CLI, or ``"debug": True`` in the global settings block of a config
    file.  BankSet-internal detail (gesture timing, chord windows, etc.)
    is gated on the per-BankSet ``bs._debug`` flag and is independent.
    """
    if config.DEBUG:
        # Wall-clock stamp so a frozen session can be lined up against
        # 'dmesg -T' / 'journalctl -k'.  This is the datum a freeze turns
        # on: when the last MIDI event actually arrived.  Every other log
        # line is downstream of this one by milliseconds, so stamping here
        # is enough to bracket the stall.  Cost is marginal next to the
        # {event} repr this line already builds, and it is gated on DEBUG.
        _t = time.time()
        print(f"\n[in] {time.strftime('%H:%M:%S', time.localtime(_t))}"
              f".{int((_t % 1) * 1000):03d} "
              f"channel={event.channel} type={event.type} {event}")

    try:
        for bankset in config.BANK_SETS:
            result = bankset.handle(event)
            if result is not None:
                if config.DEBUG:
                    print(
                        f"  [dispatch] handled by BankSet {bankset.name!r}"
                    )
                return result
    except Exception as e:
        print(f"[handler] ERROR: {e}")

    return event   # pass through unchanged (also the safe fallback on error)


def run():
    """Validate config, check JACK, set up mididings, and start the loop."""
    if config.DEBUG:
        print(f"\nStarting midi_event_remapper (backend: {config.BACKEND}).\n")

    # Check JACK before anything else.
    check_jack()

    # Validate all BankSets.
    all_errors = []
    for bs in config.BANK_SETS:
        errs, warns = bs.validate()
        all_errors.extend(errs)
        for w in warns:
            print(f"[startup] warning: {w}")
    if all_errors:
        print("\n[startup] CONFIG ERRORS:")
        for e in all_errors:
            print(f"  x {e}")
        raise SystemExit("Fix config errors before running.")
    elif config.DEBUG:
        print("[startup] All BankSets validated OK.\n")

    try:
        setup()
    except Exception as e:
        print(
            f"\n[startup] ERROR: Failed to connect to JACK.\n"
            f"  {e}\n\n"
            f"  Make sure JACK is running before starting this script.\n"
            f"  Start it with QjackCtl or: jackd -d alsa\n"
        )
        sys.exit(1)

    try:
        mididings_run(
            Process(main_handler) # >>
            #Output(port=config.PORT_INDEX, channel=config.CHANNEL)
        )
    except KeyboardInterrupt:
        pass  # clean Ctrl-C exit, message printed below
    except Exception as e:
        print(f"\n[runtime] ERROR: {e}\n")
        sys.exit(1)

    print("\nExiting midi_event_remapper.")
