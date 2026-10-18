"""loader.py

Loads external BankSet config files using ast.literal_eval.

Config files are plain Python data literals -- no imports, no code
execution.  They are safe to load from untrusted sources.

USAGE
-----
Each .py config file defines one BankSet.  Pass one or more files to
midi-remapper and they replace the built-in config.py BankSets:

    midi-remapper actition.py
    midi-remapper global.py actition.py

Files are processed in order, so global.py would be checked first
(matching the behavior of the built-in global_banks + actition_banks).

FILE FORMAT
-----------
A config file contains a single Python dict literal describing one
BankSet.  The dict may include any BankSet constructor parameters:

    {
        "name": "actition",
        "active_bank": "default",
        "long_press_ms": 300,
        "banks": {
            "default": {
                "CC0": [{"send": "CC0", "press_only": True}],
                "CC1": {
                    "single": [{"send": "CC1",  "value": 127}],
                    "double": [{"send": "CC11", "value": 127}],
                    "long":   [{"send": "PC88"}],
                },
                "CC1+CC2": {
                    "single": [{"send": "BANK", "bank": "drums"}],
                    "double": [{"send": "BANK", "bank": "ardour"}],
                },
            },
            "drums": {
                "CC0": [{"send": "CC4", "press_only": True}],
            },
        },
    }

CHORD KEYS
----------
Chord keys (tuples in config.py) are written as "CC1+CC2" in .py files
-- keys joined by "+".  Key order does not matter: "CC1+CC2" and
"CC2+CC1" are equivalent.  The loader converts them to tuples.

OPTIONAL PARAMETERS
-------------------
The following BankSet parameters may be set per-file; if omitted they
fall back to the values in config.py:

    "active_bank"           (default: "default")
    "long_press_ms"
    "multi_press_window_ms"
    "chord_window_ms"
    "debounce_ms"
    "debug"
    "data_offset"
    "_display" key          per-bank visual style for the display window,
                            placed inside each bank dict (not at the BankSet
                            level).  Recognized keys: "bg", "fg", "font_size",
                            "width", "height".  Omitted keys fall back to the
                            module defaults in bank_display.py.  Example:
                                "banks": {
                                    "default": {
                                        "_display": {"bg": "#1a1a2e",
                                                     "fg": "#e0e0ff"},
                                        "CC0": [...],
                                    },
                                    "drums": {
                                        "_display": {"bg": "#1a2e1a",
                                                     "fg": "#a0ffb0",
                                                     "font_size": 80},
                                        "CC0": [...],
                                    },
                                }

DEBUG LEVELS
------------
There are two independent debug flags:

``config.DEBUG`` (global)
    Controls dispatcher-level output: the ``[in]``, ``[dispatch]``, and
    startup lines printed by ``dispatcher.py``.  Set globally via the
    ``DEBUG`` constant in ``config.py`` or with the ``--debug`` CLI flag.

``BankSet._debug`` (per-BankSet)
    Controls BankSet-level detail: ``[BankSet:name] handle key=...``,
    gesture timing, chord windows, sequence dispatch.  Set per-BankSet
    via the ``"debug"`` key in a BankSet dict, or overridden for all
    BankSets by the ``--debug`` CLI flag.

The ``--debug`` CLI flag sets both levels simultaneously.  Setting
``"debug": true`` in a BankSet dict sets only that BankSet's internal
trace; the ``[in]`` / ``[dispatch]`` dispatcher lines will not appear
unless ``config.DEBUG`` is also True.

GLOBAL SETTINGS BLOCK
---------------------
In list-format config files, an optional settings block may appear as
the first item.  A settings block is a dict with no ``"banks"`` key,
distinguishing it from a BankSet dict.  Example::

    [
        {"debug": True},           # global settings block
        {"name": "main", "banks": { ... }},
    ]

Recognized global settings keys:

    "debug"     sets ``config.DEBUG`` (the dispatcher-level flag).
                Hot-reloadable: changing it while the program runs takes
                effect on the next event.

The ``--debug`` / ``--no-debug`` CLI flags always override this setting.
A single-dict config file (one BankSet) does not support a settings
block; use list format for files that need global settings.
"""
import ast
import textwrap
from collections import namedtuple
from pathlib import Path

# Return type of load_bankset_file.
LoadResult = namedtuple("LoadResult", ["settings", "banksets"])

from midi_event_remapper import config as global_config
from midi_event_remapper.bankset import BankSet


def _parse_chord_key(key):
    """Convert a 'CC1+CC2' string into a tuple ('CC1', 'CC2').

    Each component is uppercased so that 'cc1+cc2', 'CC1+cc2', and
    'CC1+CC2' all produce the same tuple.
    """
    parts = [k.strip().upper() for k in key.split("+")]
    return tuple(sorted(parts))


def _convert_keys(bank):
    """
    Walk a bank dict and convert keys to their canonical form:
      - 'A+B' chord strings  → sorted tuples of uppercased components
      - plain string keys    → uppercased  ('cc5' → 'CC5')
    Returns a new dict with converted keys.
    """
    result = {}
    for key, value in bank.items():
        if isinstance(key, str) and "+" in key:
            new_key = _parse_chord_key(key)
        elif isinstance(key, str):
            new_key = key.upper()
        else:
            new_key = key
        result[new_key] = value
    return result


def _make_bankset(data, default_name):
    """Construct a BankSet from a single dict, applying global defaults."""
    data = dict(data)

    if "name" not in data:
        data["name"] = default_name

    if "banks" not in data:
        raise ValueError(
            f"BankSet {data['name']!r} is missing required 'banks' key"
        )

    # Strip "_display" from each bank dict and collect into display_styles.
    # The BankSet itself never sees "_display" as an entry key.
    display_styles = {}
    converted_banks = {}
    for bank_name, bank in data["banks"].items():
        bank = dict(bank)
        if "_display" in bank:
            display_styles[bank_name] = bank.pop("_display")
        converted_banks[bank_name] = _convert_keys(bank)
    data["banks"] = converted_banks

    return BankSet(
        name                  = data["name"],
        banks                 = data["banks"],
        active_bank           = data.get("active_bank", "default"),
        output_fn             = None,
        debug                 = data.get("debug",
                                         global_config.DEBUG),
        data_offset           = data.get("data_offset",
                                         global_config.DATA_OFFSET),
        debounce_ms           = data.get("debounce_ms",
                                         global_config.DEBOUNCE_MS),
        multi_press_window_ms = data.get("multi_press_window_ms",
                                         global_config.MULTI_PRESS_WINDOW_MS),
        chord_window_ms       = data.get("chord_window_ms",
                                         global_config.CHORD_WINDOW_MS),
        long_press_ms         = data.get("long_press_ms",
                                         global_config.LONG_PRESS_MS),
        display_styles        = display_styles,
    )


_GLOBAL_SETTINGS_KEYS = frozenset({"debug"})


def load_bankset_file(path):
    """Load a BankSet config file and return a ``LoadResult(settings, banksets)``.

    ``settings`` is a dict of global settings extracted from an optional
    settings block (see module docstring).  It is empty when no settings
    block is present.  ``banksets`` is a list of BankSet instances.

    A file containing a single dict returns one BankSet (no settings block).
    A file containing a list of dicts returns one BankSet per dict; if the
    first dict has no ``"banks"`` key it is treated as a settings block.

    Parameters
    ----------
    path : str or Path

    Returns
    -------
    LoadResult

    Raises
    ------
    ValueError, FileNotFoundError
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        data = ast.literal_eval(textwrap.dedent(path.read_text()))
    except (ValueError, SyntaxError) as e:
        raise ValueError(
            f"Failed to parse config file {path}:\n  {e}\n\n"
            f"  The file must contain a single Python dict literal.\n"
            f"  No imports, function calls, or BankSet() -- just data."
        ) from e

    if isinstance(data, dict):
        return LoadResult(settings={}, banksets=[_make_bankset(data, path.stem)])

    if not isinstance(data, list):
        raise ValueError(
            f"Config file {path} must contain a dict or list of dicts, "
            f"got {type(data).__name__}"
        )
    if not data:
        raise ValueError(f"Config file {path} contains an empty list")
    if not all(isinstance(d, dict) for d in data):
        raise ValueError(
            f"Config file {path}: list items must all be dicts"
        )

    # Detect optional settings block: first item with no "banks" key.
    settings = {}
    items = data
    if "banks" not in data[0]:
        settings_raw = data[0]
        unknown = set(settings_raw) - _GLOBAL_SETTINGS_KEYS
        if unknown:
            raise ValueError(
                f"Config file {path}: unknown global settings key(s): "
                f"{sorted(unknown)}.  Recognized: {sorted(_GLOBAL_SETTINGS_KEYS)}."
            )
        settings = dict(settings_raw)
        items = data[1:]
        if not items:
            raise ValueError(
                f"Config file {path}: settings block present but no BankSets follow"
            )

    return LoadResult(
        settings = settings,
        banksets = [_make_bankset(d, path.stem) for d in items],
    )
