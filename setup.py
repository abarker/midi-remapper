"""
setup.py

Build script for the optional midi_event_remapper.midi_core Cython
extension.  The extension provides faster inner-loop functions for the
MIDI event hot path (event_key, is_release, build_event).  The pure
Python fallback in midi.py is always available if the extension is not
built or if Cython is not installed.

Usage
-----
Install Cython and build the extension in-place::

    pip install ".[rt]"
    python setup.py build_ext --inplace

Or, to install the whole package with the extension built::

    pip install ".[rt]" .
    python setup.py build_ext --inplace

The extension is automatically skipped if Cython is not available,
so ``pip install .`` always works without Cython.
"""
from setuptools import setup, Extension

try:
    from Cython.Build import cythonize

    extensions = cythonize(
        [
            Extension(
                name    = "midi_event_remapper.midi_core",
                sources = ["src/midi_event_remapper/midi_core.pyx"],
            )
        ],
        compiler_directives = {
            "language_level": "3",
            "boundscheck":    False,
            "wraparound":     False,
            "nonecheck":      False,
        },
    )
    print("Cython found -- building midi_core extension.")

except ImportError:
    extensions = []
    print(
        "Cython not found -- skipping midi_core extension.\n"
        "For RT performance install Cython first: pip install cython"
    )

setup(ext_modules=extensions)
