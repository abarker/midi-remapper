"""
test_loader.py

Tests for the .py config file loader.
"""
import pytest
import tempfile
from pathlib import Path
from conftest import make_cc

from midi_event_remapper.loader import load_bankset_file, LoadResult, _parse_chord_key, _convert_keys


# ---------------------------------------------------------------------------
# Chord key parsing
# ---------------------------------------------------------------------------

class TestChordKeyParsing:

    def test_two_keys(self):
        assert _parse_chord_key("CC1+CC2") == ("CC1", "CC2")

    def test_order_normalized(self):
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

def write_config(content):
    """Write content to a temp .py config file and return its path."""
    f = tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False
    )
    f.write(content)
    f.close()
    return Path(f.name)


class TestLoadBanksetFile:

    def test_minimal_valid_file(self):
        path = write_config('''
        {
            "name": "test",
            "banks": {
                "default": {},
            },
        }
        ''')
        result = load_bankset_file(path)
        bs = result.banksets[0]
        assert bs.name == "test"
        assert bs.active_bank == "default"

    def test_name_defaults_to_stem(self):
        path = write_config('''
        {
            "banks": {"default": {}},
        }
        ''')
        # Rename to a known stem
        named = path.parent / "mycontroller.py"
        path.rename(named)
        result = load_bankset_file(named)
        bs = result.banksets[0]
        assert bs.name == "mycontroller"

    def test_chord_keys_converted(self):
        path = write_config('''
        {
            "name": "test",
            "banks": {
                "default": {
                    "CC1+CC2": {"single": [{"send": "CC10", "value": 127}]},
                },
            },
        }
        ''')
        result = load_bankset_file(path)
        bs = result.banksets[0]
        bank = bs.banks["default"]
        # Should have a tuple key
        assert any(isinstance(k, tuple) for k in bank.keys())

    def test_direct_mapping_works(self, fake_timer):
        path = write_config('''
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
        load_result = load_bankset_file(path)
        bs = load_result.banksets[0]
        bs.set_output_fn(captured.append)
        handle_result = bs.handle(make_cc(0, value=127))
        assert handle_result is not None
        assert handle_result[0].ctrl == 4

    def test_active_bank_respected(self):
        path = write_config('''
        {
            "name": "test",
            "active_bank": "other",
            "banks": {
                "default": {},
                "other": {},
            },
        }
        ''')
        result = load_bankset_file(path)
        bs = result.banksets[0]
        assert bs.active_bank == "other"

    def test_timing_override(self):
        path = write_config('''
        {
            "name": "test",
            "long_press_ms": 250,
            "multi_press_window_ms": 200,
            "chord_window_ms": 50,
            "banks": {"default": {}},
        }
        ''')
        result = load_bankset_file(path)
        bs = result.banksets[0]
        assert bs._long_press_ms         == 250
        assert bs._multi_press_window_ms == 200
        assert bs._chord_window_ms       == 50

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_bankset_file("/nonexistent/path/file.py")

    def test_invalid_syntax_raises_valueerror(self):
        path = write_config("this is not valid python {{{")
        with pytest.raises(ValueError, match="Failed to parse"):
            load_bankset_file(path)

    def test_non_dict_content_raises_valueerror(self):
        path = write_config("[1, 2, 3]")
        with pytest.raises(ValueError, match="list items must all be dicts"):
            load_bankset_file(path)

    def test_missing_banks_key_raises_valueerror(self):
        path = write_config('{"name": "test"}')
        with pytest.raises(ValueError, match="missing required 'banks' key"):
            load_bankset_file(path)

    def test_validate_catches_errors_in_loaded_file(self):
        path = write_config('''
        {
            "name": "test",
            "banks": {
                "default": {
                    "CC1": [{"value": 127}],
                },
            },
        }
        ''')
        result = load_bankset_file(path)
        bs = result.banksets[0]
        errors, _ = bs.validate()
        assert any("missing required 'send'" in e for e in errors)

    def test_list_of_banksets(self):
        path = write_config('''
        [
            {
                "name": "global",
                "banks": {"default": {}},
            },
            {
                "name": "actition",
                "banks": {
                    "default": {
                        "CC0": [{"send": "CC4", "press_only": True}],
                    },
                },
            },
        ]
        ''')
        result = load_bankset_file(path)
        assert len(result.banksets) == 2
        assert result.banksets[0].name == "global"
        assert result.banksets[1].name == "actition"

    def test_empty_list_raises(self):
        path = write_config('[]')
        with pytest.raises(ValueError, match="empty list"):
            load_bankset_file(path)


class TestGlobalSettingsBlock:

    def test_settings_block_sets_debug(self):
        """A settings block with "debug" is parsed into result.settings."""
        content = '\n'.join([
            '[',
            '    {"debug": True},',
            '    {"name": "test", "banks": {"default": {}}},',
            ']',
        ])
        path = write_config(content)
        result = load_bankset_file(path)
        assert result.settings == {"debug": True}
        assert len(result.banksets) == 1
        path.unlink()

    def test_no_settings_block_gives_empty_settings(self):
        """A list with no settings block returns an empty settings dict."""
        content = '\n'.join([
            '[',
            '    {"name": "test", "banks": {"default": {}}},',
            ']',
        ])
        path = write_config(content)
        result = load_bankset_file(path)
        assert result.settings == {}
        assert len(result.banksets) == 1
        path.unlink()

    def test_single_dict_file_gives_empty_settings(self):
        """A single-dict file always returns an empty settings dict."""
        content = '{"name": "test", "banks": {"default": {}}}'
        path = write_config(content)
        result = load_bankset_file(path)
        assert result.settings == {}
        assert len(result.banksets) == 1
        path.unlink()

    def test_settings_block_false_debug(self):
        """A settings block with "debug": False is also valid."""
        content = '\n'.join([
            '[',
            '    {"debug": False},',
            '    {"name": "test", "banks": {"default": {}}},',
            ']',
        ])
        path = write_config(content)
        result = load_bankset_file(path)
        assert result.settings["debug"] is False
        path.unlink()

    def test_settings_block_unknown_key_raises(self):
        """An unrecognized key in a settings block raises ValueError."""
        content = '\n'.join([
            '[',
            '    {"debug": True, "typo_key": 99},',
            '    {"name": "test", "banks": {"default": {}}},',
            ']',
        ])
        path = write_config(content)
        with pytest.raises(ValueError, match="unknown global settings key"):
            load_bankset_file(path)
        path.unlink()

    def test_settings_only_list_raises(self):
        """A list with only a settings block and no BankSets raises ValueError."""
        content = '[{"debug": True}]'
        path = write_config(content)
        with pytest.raises(ValueError, match="no BankSets follow"):
            load_bankset_file(path)
        path.unlink()
