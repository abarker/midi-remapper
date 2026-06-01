"""cli.py

Command-line interface for midi_event_remapper.

Entry point: midi-remapper (defined in pyproject.toml)

Usage examples
--------------
Run with one or more config files:
    midi-remapper actition.py
    midi-remapper actition.py drums.py

Run with external files plus debug override:
    midi-remapper actition.py --debug

Validate config files without connecting to JACK:
    midi-remapper --validate actition.py
    midi-remapper actition.py --validate

List banks defined in a config file:
    midi-remapper --list-banks actition.py

Start with a specific bank active:
    midi-remapper actition.py --bank actition:drums

Override timing constants for this session:
    midi-remapper actition.py --long-press-ms 400 --multi-press-ms 250

Show a live bank name display window during performance:
    midi-remapper actition.py --display

Show the display window without an OS title bar:
    midi-remapper actition.py --no-titlebar

Remember the display window position across runs (default path):
    midi-remapper actition.py --display --save-pos

Remember the position in a specific file:
    midi-remapper actition.py --display --save-pos ~/mysetup.pos

Disable live config reloading:
    midi-remapper actition.py --no-reload

Use jack-rt backend for intra-block timestamp precision (SooperLooper):
    midi-remapper actition.py --jack-rt

Override the JACK client name (e.g. when running two instances):
    midi-remapper actition.py --client-name midi_remapper_2
"""
import argparse
import sys
from pathlib import Path


def build_parser():
    parser = argparse.ArgumentParser(
        prog        = "midi-remapper",
        description = "MIDI event remapper using mididings and JACK.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "configs",
        metavar = "FILE",
        nargs   = "+",
        help    = (
            "One or more .py config files, each describing one BankSet.  "
            "Files are plain Python dict literals (no imports, no function "
            "calls).  See the README or example.py for the full schema."
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
        help    = (
            "Enable both dispatcher-level ([in]/[dispatch]) and "
            "per-BankSet internal debug output.  Overrides any "
            '\"debug\" setting in the config file.'
        ),
    )

    parser.add_argument(
        "--no-debug",
        action  = "store_false",
        dest    = "debug",
        help    = "Disable all debug output (overrides config file setting).",
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
        "--no-titlebar",
        action  = "store_true",
        dest    = "no_titlebar",
        help    = (
            "Remove the OS title bar from the bank display window "
            "(implies --display).  Right-click the window for Exit / Cancel."
        ),
    )

    import os
    _default_pos_file = str(
        Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        / "midi-remapper" / "display.pos"
    )
    parser.add_argument(
        "--save-pos",
        nargs   = "?",
        const   = _default_pos_file,
        default = None,
        dest    = "save_pos",
        metavar = "FILE",
        help    = (
            "Save the display window position on exit and restore it on the "
            "next run (implies --display).  With no argument, uses "
            f"{_default_pos_file}.  "
            "Pass an explicit path to use a different file, e.g. when "
            "running multiple configs that need separate positions."
        ),
    )

    parser.add_argument(
        "--no-reload",
        action  = "store_true",
        dest    = "no_reload",
        help    = (
            "Disable live config file reloading.  By default, config files "
            "are watched for changes and reloaded automatically."
        ),
    )

    parser.add_argument(
        "--jack-rt",
        action  = "store_true",
        dest    = "jack_rt",
        help    = (
            "Use the mididings jack-rt backend instead of the default jack "
            "backend.  Runs the MIDI handler directly in the JACK process "
            "callback, which preserves intra-block MIDI timestamps (useful "
            "for SooperLooper loop-boundary precision).  WARNING: Python "
            "code in the RT callback can cause xruns in other JACK clients. "
            "Also calls sys.setswitchinterval(0.0001) to reduce GIL "
            "contention."
        ),
    )

    parser.add_argument(
        "--client-name",
        default = None,
        dest    = "client_name",
        metavar = "NAME",
        help    = (
            "Override the JACK client name for this session "
            "(default: CLIENT_NAME in config.py, 'midi_remapper').  "
            "Useful when running multiple instances simultaneously."
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
        banksets       = []
        file_debug     = None   # last "debug" value seen in a settings block
        for path in args.configs:
            try:
                result = load_bankset_file(path)
            except (FileNotFoundError, ValueError) as e:
                print(f"\n[cli] ERROR loading {path}:\n  {e}\n")
                sys.exit(1)
            # Global settings block: "debug" sets config.DEBUG (dispatcher
            # level).  Collected here so the --debug CLI flag can override
            # it below after all files are processed.
            if "debug" in result.settings:
                file_debug = result.settings["debug"]
            banksets.extend(result.banksets)
        # Apply file-level global debug before the CLI flag can override it.
        if file_debug is not None:
            global_config.DEBUG = file_debug
    # FILE is required (nargs='+'), so args.configs is always non-empty.

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
            errs, warns = bs.validate()
            if warns:
                print(f"\n[validate] BankSet {bs.name!r} warnings:")
                for w in warns:
                    print(f"  ! {w}")
            if errs:
                print(f"\n[validate] BankSet {bs.name!r} errors:")
                for e in errs:
                    print(f"  x {e}")
                all_errors.extend(errs)
            elif not warns:
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
    # CLI --debug / --no-debug overrides both config.DEBUG (dispatcher level)
    # and bs._debug (BankSet level).  File-level "debug" was applied above
    # during loading; this line overrides that if the flag was given.
    if args.debug is not None:
        global_config.DEBUG = args.debug

    # --display: start the bank name window and wire it into each BankSet.
    # --no-titlebar and --save-pos both imply --display.
    display = None
    if args.display or args.no_titlebar or args.save_pos:
        try:
            from midi_event_remapper.bank_display import BankDisplay
            display = BankDisplay(
                no_titlebar = args.no_titlebar,
                save_pos    = args.save_pos,
            )
            display.start()
            for bs in banksets:
                bs._display_fn = display.update
            # Show initial state.
            for bs in banksets:
                if bs.active_bank != "default" or len(bs.banks) > 1:
                    display.update(bs.name, bs.active_bank,
                                   bs._display_styles.get(bs.active_bank))
                    break
            else:
                if banksets:
                    bs = banksets[0]
                    display.update(bs.name, bs.active_bank,
                                   bs._display_styles.get(bs.active_bank))
        except ImportError:
            print(
                "[cli] WARNING: tkinter is not available -- "
                "--display requires tkinter (usually part of the Python "
                "standard library; install python3-tk on Debian/Ubuntu)."
            )
            display = None

    # Apply jack-rt backend if requested.  setswitchinterval and BACKEND must
    # be set before mididings starts its threads.  gc.collect()+gc.freeze()
    # are applied later, just before dispatcher.run(), so all startup objects
    # are included in the freeze.  A startup warning is always printed because
    # the xrun risk affects other JACK clients, not just this program.
    if args.jack_rt:
        import sys as _sys
        _sys.setswitchinterval(0.0001)
        global_config.BACKEND = 'jack-rt'
        from midi_event_remapper.midi import _CYTHON_CORE
        _cython_note = (
            "  Cython midi_core extension active -- hot path uses C types.\n"
            if _CYTHON_CORE else
            "  Cython midi_core extension NOT built (pure Python hot path).\n"
            "  Build it for better RT performance:\n"
            "    pip install \'.[rt]\' && python setup.py build_ext --inplace\n"
        )
        print(
            "[startup] jack-rt backend enabled.\n"
            "  MIDI handler runs in the JACK RT callback.\n"
            "  sys.setswitchinterval(0.0001) set to reduce GIL contention.\n"
            "  gc.collect() + gc.freeze() will run after startup completes.\n"
            + _cython_note +
            "  WARNING: slow or blocking Python may cause xruns in all\n"
            "  JACK clients.  Keep the handler lean.\n"
        )

    if args.client_name:
        global_config.CLIENT_NAME = args.client_name

    # Start the live reloader when external config files are in use.
    reloader = None
    if args.configs and not args.no_reload:
        from midi_event_remapper.reloader import ConfigReloader
        reloader = ConfigReloader(
            paths         = [p for p in args.configs],
            global_config = global_config,
            display       = display,
            debug         = args.debug is True,
        )
        reloader.start()
        if global_config.DEBUG:
            print("[reload] Watching config files for changes.")

    # With jack-rt, freeze the GC permanent generation immediately before
    # starting the event loop.  gc.collect() first clears any cycles from
    # startup; gc.freeze() then moves all live objects into a generation
    # the collector never scans again.  Objects created after this point
    # (runtime state, reloaded BankSets) are still tracked and collected
    # normally -- so genuine memory cycles at runtime are still cleaned up.
    if args.jack_rt:
        import gc as _gc
        _gc.collect()
        _gc.freeze()
        if global_config.DEBUG:
            counts = _gc.get_count()
            frozen = _gc.get_freeze_count()
            print(f"[startup] GC frozen: {frozen} objects in permanent "
                  f"generation, runtime tracking still active.")

    try:
        dispatcher.run()
    finally:
        if reloader is not None:
            reloader.stop()
        if display is not None:
            display.stop()


if __name__ == "__main__":
    main()
