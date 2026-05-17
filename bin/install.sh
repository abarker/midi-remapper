#!/usr/bin/env bash
#
# bin/install.sh
#
# Install midi-event-remapper from the project root.
#
# The package is not on PyPI.  Run this script from the directory that
# contains pyproject.toml (the project root), or from anywhere -- it
# locates the project root automatically from its own path.
#
# Called with no arguments: shows an interactive menu.
#
# Usage (non-interactive)
# -----------------------
#   bin/install.sh                  Regular install, pure Python
#   bin/install.sh --dev            Editable install for development
#   bin/install.sh --cython         Build the optional Cython RT extension
#   bin/install.sh --no-tests       Skip the post-install test run
#
# Options may be combined in any order, e.g.:
#   bin/install.sh --dev --cython
#
# Modes
# -----
# Regular install (default)
#   Installs the package into the active Python environment.  Changes
#   to the source after this point are NOT reflected until you re-run.
#
# Editable install (--dev)
#   Installs in editable mode so source changes take effect immediately
#   without reinstalling.  Also installs pytest and other dev extras.
#
# Cython extension (--cython)
#   Builds midi_core, which accelerates the MIDI event hot path.  Most
#   users do not need this.  It may help reduce xruns when using
#   --jack-rt if the pure Python overhead is contributing; see the
#   README for details.  Re-run the script with --cython any time
#   midi_core.pyx is edited to recompile.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

DEV=0
CYTHON=0
RUN_TESTS=1

# ── Interactive menu (no arguments) ───────────────────────────────────────

if [[ $# -eq 0 ]]; then
    echo ""
    echo "midi-event-remapper installer"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1)  Regular install        pure Python              [recommended]"
    echo "  2)  Regular install        with Cython RT extension"
    echo "  3)  Editable (dev) install pure Python              [for development]"
    echo "  4)  Editable (dev) install with Cython RT extension"
    echo ""
    echo "  The Cython extension is optional.  It may reduce xruns when"
    echo "  using --jack-rt.  Re-run this script to recompile after editing"
    echo "  midi_core.pyx."
    echo ""
    echo "  q)  Quit"
    echo ""
    read -rp "Enter choice [1-4]: " choice
    echo ""

    case "$choice" in
        1) DEV=0; CYTHON=0 ;;
        2) DEV=0; CYTHON=1 ;;
        3) DEV=1; CYTHON=0 ;;
        4) DEV=1; CYTHON=1 ;;
        q|Q) echo "Aborted."; exit 0 ;;
        *)
            echo "Invalid choice: $choice" >&2
            exit 1
            ;;
    esac

    read -rp "Run post-install tests? [Y/n]: " yn
    echo ""
    case "$yn" in
        n|N|no|No|NO) RUN_TESTS=0 ;;
        *)             RUN_TESTS=1 ;;
    esac

else
    # ── Argument parsing (non-interactive) ────────────────────────────────
    for arg in "$@"; do
        case "$arg" in
            --dev)       DEV=1 ;;
            --cython)    CYTHON=1 ;;
            --no-tests)  RUN_TESTS=0 ;;
            -h|--help)
                sed -n '2,40p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \{0,1\}//'
                exit 0
                ;;
            *)
                echo "Unknown option: $arg" >&2
                echo "Usage: $0 [--dev] [--cython] [--no-tests]" >&2
                exit 1
                ;;
        esac
    done
fi

# ── Sanity check ──────────────────────────────────────────────────────────

cd "$PROJECT_ROOT"

if [[ ! -f pyproject.toml ]]; then
    echo "ERROR: pyproject.toml not found in $PROJECT_ROOT" >&2
    exit 1
fi

# ── Install ───────────────────────────────────────────────────────────────

if [[ $DEV -eq 1 ]]; then
    if [[ $CYTHON -eq 1 ]]; then
        echo "=== Installing (editable, dev + rt extras) ==="
        pip install -e ".[dev,rt]"
    else
        echo "=== Installing (editable, dev extras) ==="
        pip install -e ".[dev]"
    fi
else
    if [[ $CYTHON -eq 1 ]]; then
        echo "=== Installing (with rt extras) ==="
        pip install ".[rt]"
    else
        echo "=== Installing ==="
        pip install .
    fi
fi

# ── Build Cython extension in-place (editable installs only) ─────────────
#
# For regular installs pip drives the build via setup.py automatically.
# For editable installs the .so must be compiled separately because pip
# does not invoke setup.py build_ext for editable mode.
#
# Re-run this script with --cython (or choose option 2/4 in the menu)
# any time midi_core.pyx is edited.

if [[ $DEV -eq 1 && $CYTHON -eq 1 ]]; then
    echo ""
    echo "=== Building Cython extension in-place ==="
    python setup.py build_ext --inplace
fi

# ── Verify ────────────────────────────────────────────────────────────────

echo ""
echo "=== Verifying installation ==="
python - << 'PYEOF'
from midi_event_remapper.midi import _CYTHON_CORE
if _CYTHON_CORE:
    print("midi_core Cython extension: OK (RT path active)")
else:
    print("midi_core Cython extension: not built (pure Python fallback active)")

import midi_event_remapper.cli
print("midi-event-remapper: installed OK")
PYEOF

# ── Tests ─────────────────────────────────────────────────────────────────

if [[ $RUN_TESTS -eq 1 ]]; then
    if ! python -c "import pytest" 2>/dev/null; then
        echo ""
        echo "pytest not installed -- skipping tests"
        echo "(install dev extras with --dev or menu option 3/4 to include pytest)"
    else
        if [[ $CYTHON -eq 1 ]]; then
            echo ""
            echo "=== Running tests (Cython path) ==="
            pytest

            echo ""
            echo "=== Running tests (pure Python fallback) ==="
            MIDI_REMAPPER_NO_CYTHON=1 pytest
        else
            echo ""
            echo "=== Running tests ==="
            MIDI_REMAPPER_NO_CYTHON=1 pytest
        fi
    fi
fi

echo ""
echo "=== Done ==="
