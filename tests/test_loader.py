"""
test_loader.py

Tests for the .mer config file loader.
"""
import pytest
import tempfile
from pathlib import Path
from conftest import make_cc

from midi_event_remapper.loader import load_bankset_file, _parse_chord_key, _convert_keys


# ---------------------------------------------------------------------------
# Chord key parsing
# ---------------------------------------------------------------------------

class TestChordKeyParsing:

    def test_two_keys(self):
        assert _parse_chord_key("CC1+CC2") == ("CC1", "CC2")

    def test_order_normalised(self):
        # Keys are sorted so CC2+CC1 and CC1+CC2 produce the same tuple.
        assert _parse_chord_key("CC2+CC1") == _parse_chord_key("CC1+CC2")

    def test_three_keys(self):
        result = _parse_chord_key("CC1+CC2+CC3")
        assert set(result) == {"CC1", "CC2", "CC3"}

    def test_whitespace_stripped(self):
        assert _parse_chord_key("CC1 + CC2") == ("CC1", "CC2")


class TestConvertKeys:

    def test_chord_key_converted(self):
        bank = {"CC1+CC2": {"single": []}}
        result = _convert_keys(bank)
        assert ("CC1", "CC2") in result or ("CC2", "CC1") in result

    def test_plain_key_unchanged(self):
        bank = {"CC0": [{"send": "CC4"}]}
        result = _convert_keys(bank)
        assert "CC0" in result

    def test_mixed_keys(self):
        bank = {
            "CC0": [{"send": "CC4"}],
            "CC1+CC2": {"single": [{"send": "BANK", "bank": "drums"}]},
        }
        result = _convert_keys(bank)
        assert "CC0" in result
        assert any(isinstance(k, tuple) for k in result)


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def write_mer(content):
    """Write content to a temp .mer file and return its path."""
    f = tempfile.NamedTemporaryFile(
        suffix=".mer", mode="w", delete=False
    )
    f.write(content)
    f.close()
    return Path(f.name)


class TestLoadBanksetFile:

    def test_minimal_valid_file(self):
        path = write_mer('''
        {
            "name": "test",
            "banks": {
                "default": {},
            },
        }
        ''')
        bs = load_bankset_file(path)
        assert bs.name == "test"
        assert bs.active_bank == "default"

    def test_name_defaults_to_stem(self):
        path = write_mer('''
        {
            "banks": {"default": {}},
        }
        ''')
        # Rename to a known stem
        named = path.parent / "mycontroller.mer"
        path.rename(named)
        bs = load_bankset_file(named)
        assert bs.name == "mycontroller"

    def test_chord_keys_converted(self):
        path = write_mer('''
        {
            "name": "test",
            "banks": {
                "default": {
                    "CC1+CC2": {"single": [{"send": "CC10", "value": 127}]},
                },
            },
        }
        ''')
        bs = load_bankset_file(path)
        bank = bs.banks["default"]
        # Should have a tuple key
        assert any(isinstance(k, tuple) for k in bank.keys())

    def test_direct_mapping_works(self, fake_timer):
        path = write_mer('''
        {
            "name": "test",
            "banks": {
                "default": {
                    "CC0": [{"send": "CC4", "press_only": True}],
                },
            },
        }
        ''')
        captured = []
        bs = load_bankset_file(path)
        bs.set_output_fn(captured.append)
        result = bs.handle(make_cc(0, value=127))
        assert result is not None
        assert result[0].ctrl == 4

    def test_active_bank_respected(self):
        path = write_mer('''
        {
            "name": "test",
            "active_bank": "other",
            "banks": {
                "default": {},
                "other": {},
            },
        }
        ''')
        bs = load_bankset_file(path)
        assert bs.active_bank == "other"

    def test_timing_override(self):
        path = write_mer('''
        {
            "name": "test",
            "long_press_ms": 250,
            "multi_press_window_ms": 200,
            "chord_window_ms": 50,
            "banks": {"default": {}},
        }
        ''')
        bs = load_bankset_file(path)
        assert bs._long_press_ms         == 250
        assert bs._multi_press_window_ms == 200
        assert bs._chord_window_ms       == 50

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_bankset_file("/nonexistent/path/file.mer")

    def test_invalid_syntax_raises_valueerror(self):
        path = write_mer("this is not valid python {{{")
        with pytest.raises(ValueError, match="Failed to parse"):
            load_bankset_file(path)

    def test_non_dict_content_raises_valueerror(self):
        path = write_mer("[1, 2, 3]")
        with pytest.raises(ValueError, match="must contain a dict"):
            load_bankset_file(path)

    def test_missing_banks_key_raises_valueerror(self):
        path = write_mer('{"name": "test"}')
        with pytest.raises(ValueError, match="missing required 'banks' key"):
            load_bankset_file(path)

    def test_validate_catches_errors_in_loaded_file(self):
        path = write_mer('''
        {
            "name": "test",
            "banks": {
                "default": {
                    "CC1": [{"value": 127}],
                },
            },
        }
        ''')
        bs = load_bankset_file(path)
        errors = bs.validate()
        assert any("missing required 'send'" in e for e in errors)
