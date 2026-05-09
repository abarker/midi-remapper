#!/bin/bash
# install_dev.sh
# Install midi-event-remapper in editable mode with dev and rt extras,
# compile the Cython extension in-place, then run the test suite.
# Run from the project root directory.
#
# The test suite exercises both the pure Python and Cython implementations
# transparently.  mock_mididings uses integer event type constants so that
# the Cython extension (which stores event.type as a C int) loads and runs
# correctly under the mock.

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
echo "=== Running tests ==="
pytest
