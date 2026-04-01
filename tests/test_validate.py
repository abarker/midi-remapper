"""
test_validate.py

Tests for BankSet.validate(): config error detection at startup.
"""
import pytest
from conftest import make_bankset


def errors_for(banks, active_bank="default", data_offset=1):
    bs, _ = make_bankset(banks, active_bank=active_bank,
                         data_offset=data_offset)
    return bs.validate()


def assert_clean(banks, **kwargs):
    assert errors_for(banks, **kwargs) == []


def assert_error(banks, fragment, **kwargs):
    errs = errors_for(banks, **kwargs)
    assert any(fragment in e for e in errs), \
        f"Expected fragment {fragment!r} in errors, got: {errs}"


# ---------------------------------------------------------------------------
# Clean configs
# ---------------------------------------------------------------------------

class TestClean:

    def test_empty_bank_is_valid(self):
        assert_clean({"default": {}})

    def test_direct_mapping_valid(self):
        assert_clean({"default": {
            "PC5": [{"send": "NOTE36"}],
        }})

    def test_toggle_valid(self):
        assert_clean({"default": {
            "CC22": {
                "a": [{"send": "CC40", "value": 127}],
                "b": [{"send": "CC40", "value": 0}],
            },
        }})

    def test_gesture_single_only_valid(self):
        assert_clean({"default": {
            "CC0": {"single": [{"send": "CC10", "value": 1}]},
        }})

    def test_gesture_long_valid(self):
        assert_clean({"default": {
            "CC30": {
                "single": [{"send": "PC1"}],
                "long":   [{"send": "PC2"}],
            },
        }})

    def test_gesture_multi_valid(self):
        assert_clean({"default": {
            "PC4": {
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})

    def test_gesture_combined_valid(self):
        assert_clean({"default": {
            "CC0": {
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
                "long":   [{"send": "CC12", "value": 3}],
            },
        }})

    def test_gesture_note_long_valid(self):
        assert_clean({"default": {
            "NOTE60": {
                "single": [{"send": "CC10", "value": 127}],
                "long":   [{"send": "CC11", "value": 127}],
            },
        }})

    def test_chord_valid(self):
        assert_clean({"default": {
            ("PC4", "PC5"): {
                "single": [{"send": "CC99", "value": 127}],
            },
        }})

    def test_bank_send_valid(self):
        assert_clean({
            "default": {
                "PC1": [{"send": "BANK", "bank": "other"}],
            },
            "other": {},
        })

    def test_trigger_value_int_valid(self):
        assert_clean({"default": {
            "CC0": {
                "trigger_value": 127,
                "single": [{"send": "CC10", "value": 1}],
            },
        }})

    def test_trigger_value_range_valid(self):
        assert_clean({"default": {
            "CC0": {
                "trigger_value": "64-127",
                "single": [{"send": "CC10", "value": 1}],
            },
        }})

    def test_trigger_value_list_valid(self):
        assert_clean({"default": {
            "CC0": {
                "trigger_value": [0, "64-127"],
                "single": [{"send": "CC10", "value": 1}],
            },
        }})


# ---------------------------------------------------------------------------
# Missing / malformed send
# ---------------------------------------------------------------------------

class TestSendErrors:

    def test_missing_send_key(self):
        assert_error({"default": {
            "PC5": [{"value": 64}],
        }}, "missing required 'send' key")

    def test_unrecognised_send_prefix(self):
        assert_error({"default": {
            "PC5": [{"send": "XY42"}],
        }}, "unrecognised send")

    def test_malformed_pc_send(self):
        assert_error({"default": {
            "PC5": [{"send": "PCabc"}],
        }}, "malformed send")

    def test_malformed_cc_send(self):
        assert_error({"default": {
            "CC5": [{"send": "CCabc"}],
        }}, "malformed send")

    def test_malformed_note_send(self):
        assert_error({"default": {
            "PC5": [{"send": "NOTEabc"}],
        }}, "malformed send")

    def test_velocity_on_cc_send_caught(self):
        assert_error({"default": {
            "PC5": [{"send": "CC10", "velocity": 127}],
        }}, "did you mean 'value'")

    def test_value_on_note_send_caught(self):
        assert_error({"default": {
            "PC5": [{"send": "NOTE36", "value": 127}],
        }}, "did you mean 'velocity'")


# ---------------------------------------------------------------------------
# Out-of-range values
# ---------------------------------------------------------------------------

class TestRangeErrors:

    def test_pc0_invalid_with_data_offset_1(self):
        assert_error({"default": {
            "CC1": [{"send": "PC0"}],
        }}, "out of range", data_offset=1)

    def test_pc1_valid_with_data_offset_1(self):
        assert_clean({"default": {
            "CC1": [{"send": "PC1"}],
        }}, data_offset=1)

    def test_pc0_valid_with_data_offset_0(self):
        assert_clean({"default": {
            "CC1": [{"send": "PC0"}],
        }}, data_offset=0)

    def test_pc128_valid_with_data_offset_1(self):
        assert_clean({"default": {
            "CC1": [{"send": "PC128"}],
        }}, data_offset=1)

    def test_pc129_invalid_with_data_offset_1(self):
        assert_error({"default": {
            "CC1": [{"send": "PC129"}],
        }}, "out of range", data_offset=1)

    def test_cc_number_out_of_range(self):
        assert_error({"default": {
            "PC1": [{"send": "CC128"}],
        }}, "out of range")

    def test_note_number_out_of_range(self):
        assert_error({"default": {
            "PC1": [{"send": "NOTE128"}],
        }}, "out of range")


# ---------------------------------------------------------------------------
# Structural errors
# ---------------------------------------------------------------------------

class TestStructuralErrors:

    def test_toggle_missing_state_b(self):
        assert_error({"default": {
            "CC22": {
                "a": [{"send": "CC40", "value": 127}],
            },
        }}, "missing required state 'b'")

    def test_toggle_missing_state_a(self):
        assert_error({"default": {
            "CC22": {
                "b": [{"send": "CC40", "value": 0}],
            },
        }}, "missing required state 'a'")

    def test_bank_send_missing_bank_key(self):
        assert_error({"default": {
            "PC1": [{"send": "BANK"}],
        }}, "BANK send missing 'bank' key")

    def test_bank_send_unknown_target(self):
        assert_error({"default": {
            "PC1": [{"send": "BANK", "bank": "nonexistent"}],
        }}, "unknown bank")

    def test_active_bank_not_in_banks(self):
        bs, _ = make_bankset({"default": {}}, active_bank="missing")
        errs = bs.validate()
        assert any("active_bank" in e for e in errs)

    def test_unclassifiable_entry(self):
        bs, _ = make_bankset({"default": {
            "PC1": {"unknown_key": "something"},
        }})
        errs = bs.validate()
        assert any("cannot classify" in e for e in errs)

    def test_multiple_errors_all_reported(self):
        errs = errors_for({"default": {
            "PC1": [{"value": 1}],
            "PC2": [{"send": "CC128"}],
            "PC3": [{"send": "PCabc"}],
        }})
        assert len(errs) == 3

    def test_long_on_pc_key_caught(self):
        # PC events have no release signal; 'long' is invalid for PC keys.
        assert_error({"default": {
            "PC4": {
                "single": [{"send": "CC10", "value": 1}],
                "long":   [{"send": "CC11", "value": 1}],
            },
        }}, "momentary input")

    def test_trigger_value_invalid_syntax(self):
        assert_error({"default": {
            "CC0": {
                "trigger_value": "not-a-number",
                "single": [{"send": "CC10", "value": 1}],
            },
        }}, "invalid trigger_value")
