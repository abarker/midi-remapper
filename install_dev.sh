#!/bin/bash
# install_dev.sh
# Install midi-event-remapper in editable mode with dev and rt extras,
# compile the Cython extension in-place, then run the test suite in
# both modes to verify both implementations.
# Run from the project root directory.

set -e

echo "=== Installing (editable, dev + rt extras) ==="
pip install -e ".[dev,rt]"

echo ""
echo "=== Building Cython extension ==="
python setup.py build_ext --inplace

echo ""
echo "=== Verifying Cython extension ==="
python -c "
from midi_event_remapper.midi import _CYTHON_CORE
print('midi_core Cython extension:', 'OK' if _CYTHON_CORE else 'NOT FOUND')
"

echo ""
echo "=== Running tests (Cython path) ==="
pytest

echo ""
echo "=== Running tests (pure Python fallback, MIDI_REMAPPER_NO_CYTHON=1) ==="
MIDI_REMAPPER_NO_CYTHON=1 pytest
