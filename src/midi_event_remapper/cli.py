"""
cli.py

Command-line interface for midi_event_remapper.

Entry point: midi-remapper (defined in pyproject.toml)

Usage examples
--------------
Run with built-in config.py settings:
    midi-remapper

Run with one or more external config files (replaces built-in BankSets):
    midi-remapper actition.mer drums.mer

Run with external files plus debug override:
    midi-remapper actition.mer --debug

Validate config files without connecting to JACK:
    midi-remapper --validate actition.mer
    midi-remapper actition.mer --validate

List banks defined in a config file:
    midi-remapper --list-banks actition.mer

Start with a specific bank active:
    midi-remapper actition.mer --bank actition:drums

Override timing constants for this session:
    midi-remapper actition.mer --long-press-ms 400 --multi-press-ms 250

Show a live bank name display window during performance:
    midi-remapper actition.mer --display
"""
import argparse
import sys
from pathlib import Path


def build_parser():
    parser = argparse.ArgumentParser(
        prog        = "midi-remapper",
        description = "MIDI event remapper using mididings and JACK.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Config files are plain Python dict literals (no imports).\n"
            "Chord keys use '+' notation: 'CC1+CC2' instead of ('CC1','CC2').\n"
            "See the config.py docstring for the full schema.\n"
        ),
    )

    parser.add_argument(
        "configs",
        metavar = "FILE",
        nargs   = "*",
        help    = (
            "One or more .mer (or .py) config files, each describing one "
            "BankSet.  If none are given, the built-in config.py is used."
        ),
    )

    parser.add_argument(
        "--validate", "-V",
        action  = "store_true",
        help    = "Validate config files and exit without connecting to JACK.",
    )

    parser.add_argument(
        "--list-banks", "-l",
        action  = "store_true",
        dest    = "list_banks",
        help    = "Print the banks defined in each config file and exit.",
    )

    parser.add_argument(
        "--bank", "-b",
        metavar = "BANKSET:BANK",
        action  = "append",
        default = [],
        help    = (
            "Override the starting bank for a BankSet, e.g. "
            "'actition:drums'.  May be repeated for multiple BankSets."
        ),
    )

    parser.add_argument(
        "--debug",
        action  = "store_true",
        default = None,
        help    = "Enable debug output (overrides config file setting).",
    )

    parser.add_argument(
        "--no-debug",
        action  = "store_false",
        dest    = "debug",
        help    = "Disable debug output.",
    )

    parser.add_argument(
        "--long-press-ms",
        metavar = "MS",
        type    = int,
        default = None,
        dest    = "long_press_ms",
        help    = "Override LONG_PRESS_MS for this session.",
    )

    parser.add_argument(
        "--multi-press-ms",
        metavar = "MS",
        type    = int,
        default = None,
        dest    = "multi_press_window_ms",
        help    = "Override MULTI_PRESS_WINDOW_MS for this session.",
    )

    parser.add_argument(
        "--chord-ms",
        metavar = "MS",
        type    = int,
        default = None,
        dest    = "chord_window_ms",
        help    = "Override CHORD_WINDOW_MS for this session.",
    )

    parser.add_argument(
        "--display", "-d",
        action  = "store_true",
        help    = (
            "Open a window showing the current bank name in large text. "
            "Useful during live performance to confirm bank switches."
        ),
    )

    parser.add_argument(
        "--version",
        action  = "version",
        version = "midi-remapper 0.1.0",
    )

    return parser


def _parse_bank_overrides(bank_args):
    """Parse ['actition:drums', 'global:default'] into a dict."""
    overrides = {}
    for arg in bank_args:
        if ":" not in arg:
            print(
                f"[cli] ERROR: --bank argument must be 'BANKSET:BANK', "
                f"got {arg!r}"
            )
            sys.exit(1)
        bankset_name, bank_name = arg.split(":", 1)
        overrides[bankset_name] = bank_name
    return overrides


def _apply_overrides(banksets, args, bank_overrides):
    """Apply CLI overrides to a list of BankSet instances."""
    for bs in banksets:
        # --bank override
        if bs.name in bank_overrides:
            target = bank_overrides[bs.name]
            if target not in bs.banks:
                print(
                    f"[cli] ERROR: BankSet {bs.name!r} has no bank "
                    f"{target!r}. Available: {list(bs.banks.keys())}"
                )
                sys.exit(1)
            bs.active_bank = target

        # --debug / --no-debug override
        if args.debug is not None:
            bs._debug = args.debug

        # Timing overrides
        if args.long_press_ms is not None:
            bs._long_press_ms = args.long_press_ms
        if args.multi_press_window_ms is not None:
            bs._multi_press_window_ms = args.multi_press_window_ms
        if args.chord_window_ms is not None:
            bs._chord_window_ms = args.chord_window_ms


def main():
    """Entry point for the midi-remapper command."""
    parser  = build_parser()
    args    = parser.parse_args()

    from midi_event_remapper import config as global_config
    from midi_event_remapper.loader import load_bankset_file

    # ------------------------------------------------------------------
    # Build BankSet list
    # ------------------------------------------------------------------
    if args.configs:
        banksets = []
        for path in args.configs:
            try:
                loaded = load_bankset_file(path)
                # load_bankset_file always returns a list; extend flattens it.
                for item in loaded:
                    if isinstance(item, list):
                        banksets.extend(item)  # guard against accidental nesting
                    else:
                        banksets.append(item)
            except (FileNotFoundError, ValueError) as e:
                print(f"\n[cli] ERROR loading {path}:\n  {e}\n")
                sys.exit(1)
    else:
        banksets = list(global_config.BANK_SETS)

    bank_overrides = _parse_bank_overrides(args.bank)
    _apply_overrides(banksets, args, bank_overrides)

    # ------------------------------------------------------------------
    # --list-banks
    # ------------------------------------------------------------------
    if args.list_banks:
        for bs in banksets:
            print(f"\nBankSet: {bs.name!r}  (active: {bs.active_bank!r})")
            for bank_name, bank in bs.banks.items():
                marker = " *" if bank_name == bs.active_bank else "  "
                keys = [
                    ("+".join(sorted(k)) if isinstance(k, tuple) else k)
                    for k in bank.keys()
                ]
                print(f"  {marker} {bank_name}: {keys}")
        return

    # ------------------------------------------------------------------
    # --validate
    # ------------------------------------------------------------------
    if args.validate:
        all_errors = []
        for bs in banksets:
            errs = bs.validate()
            if errs:
                print(f"\n[validate] BankSet {bs.name!r}:")
                for e in errs:
                    print(f"  x {e}")
                all_errors.extend(errs)
            else:
                print(f"[validate] BankSet {bs.name!r}: OK")
        if all_errors:
            sys.exit(1)
        return

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    from midi_event_remapper import dispatcher

    # Override the global BANK_SETS used by the dispatcher.
    global_config.BANK_SETS = banksets
    # Apply debug to global config too (affects dispatcher print calls).
    if args.debug is not None:
        global_config.DEBUG = args.debug

    # --display: start the bank name window and wire it into each BankSet.
    display = None
    if args.display:
        try:
            from midi_event_remapper.bank_display import BankDisplay
            display = BankDisplay()
            display.start()
            for bs in banksets:
                bs._display_fn = display.update
            # Show initial state.
            for bs in banksets:
                if bs.active_bank != "default" or len(bs.banks) > 1:
                    display.update(bs.name, bs.active_bank)
                    break
            else:
                if banksets:
                    display.update(banksets[0].name, banksets[0].active_bank)
        except ImportError:
            print(
                "[cli] WARNING: tkinter is not available -- "
                "--display requires tkinter (usually part of the Python "
                "standard library; install python3-tk on Debian/Ubuntu)."
            )
            display = None

    try:
        dispatcher.run()
    finally:
        if display is not None:
            display.stop()


if __name__ == "__main__":
    main()
