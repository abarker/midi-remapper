"""
loader.py

Loads external BankSet config files using ast.literal_eval.

Config files are plain Python data literals -- no imports, no code
execution.  They are safe to load from untrusted sources.

USAGE
-----
Each .mer file defines one BankSet.  Pass one or more files to
midi-remapper and they replace the built-in config.py BankSets:

    midi-remapper actition.mer
    midi-remapper global.mer actition.mer

Files are processed in order, so global.mer would be checked first
(matching the behaviour of the built-in global_banks + actition_banks).

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
Chord keys (tuples in config.py) are written as "CC1+CC2" in .mer files
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
"""
import ast
import textwrap
from pathlib import Path

from midi_event_remapper import config as global_config
from midi_event_remapper.bankset import BankSet


def _parse_chord_key(key):
    """Convert a 'CC1+CC2' string into a tuple ('CC1', 'CC2')."""
    parts = [k.strip() for k in key.split("+")]
    return tuple(sorted(parts))


def _convert_keys(bank):
    """
    Walk a bank dict and convert any 'A+B' string keys into tuples.
    Returns a new dict with converted keys.
    """
    result = {}
    for key, value in bank.items():
        if isinstance(key, str) and "+" in key:
            new_key = _parse_chord_key(key)
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

    data["banks"] = {
        bank_name: _convert_keys(bank)
        for bank_name, bank in data["banks"].items()
    }

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
    )


def load_bankset_file(path):
    """
    Load a BankSet config file and return a list of BankSet instances.

    A file containing a single dict returns a one-element list.
    A file containing a list of dicts returns one BankSet per dict.

    Parameters
    ----------
    path : str or Path

    Returns
    -------
    list[BankSet]

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
        return [_make_bankset(data, path.stem)]
    elif isinstance(data, list):
        if not data:
            raise ValueError(f"Config file {path} contains an empty list")
        if not all(isinstance(d, dict) for d in data):
            raise ValueError(
                f"Config file {path}: must contain a dict or list of dicts"
            )
        return [_make_bankset(d, path.stem) for d in data]
    else:
        raise ValueError(
            f"Config file {path} must contain a dict or list of dicts, "
            f"got {type(data).__name__}"
        )
