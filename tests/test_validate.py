"""
test_validate.py

Tests for BankSet.validate(): config error detection at startup.
"""
import pytest
from conftest import make_bankset


def errors_for(banks, active_bank="default", data_offset=1):
    bs, _ = make_bankset(banks, active_bank=active_bank,
                         data_offset=data_offset)
    errs, _warns = bs.validate()
    return errs


def warnings_for(banks, active_bank="default", data_offset=1):
    bs, _ = make_bankset(banks, active_bank=active_bank,
                         data_offset=data_offset)
    _errs, warns = bs.validate()
    return warns


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
        errs, _ = bs.validate()
        assert any("active_bank" in e for e in errs)

    def test_unclassifiable_entry(self):
        bs, _ = make_bankset({"default": {
            "PC1": {"unknown_key": "something"},
        }})
        errs, _ = bs.validate()
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

    def test_long_in_chord_entry_caught(self):
        # Chords have no individual release signal; 'long' is invalid.
        assert_error({"default": {
            ("CC1", "CC2"): {
                "single": [{"send": "CC10", "value": 1}],
                "long":   [{"send": "CC11", "value": 1}],
            },
        }}, "no individual release signal")

    def test_repeat_on_pc_key_caught(self):
        assert_error({"default": {
            "PC4": {
                "repeat": [{"send": "CC10", "value": 1}],
            },
        }}, "momentary")

    def test_repeat_and_long_together_caught(self):
        assert_error({"default": {
            "CC0": {
                "long":   [{"send": "CC10", "value": 1}],
                "repeat": [{"send": "CC11", "value": 1}],
            },
        }}, "cannot both be defined")

    def test_trigger_value_invalid_syntax(self):
        assert_error({"default": {
            "CC0": {
                "trigger_value": "not-a-number",
                "single": [{"send": "CC10", "value": 1}],
            },
        }}, "invalid trigger_value")

class TestCmdValidation:

    def test_cmd_valid(self):
        assert_clean({"default": {
            "PC5": [{"send": "CMD", "cmd": "echo hello"}],
        }})

    def test_cmd_missing_cmd_key(self):
        assert_error({"default": {
            "PC5": [{"send": "CMD"}],
        }}, "missing required 'cmd' key")

    def test_cmd_empty_string(self):
        assert_error({"default": {
            "PC5": [{"send": "CMD", "cmd": ""}],
        }}, "non-empty string")

    def test_cmd_whitespace_only(self):
        assert_error({"default": {
            "PC5": [{"send": "CMD", "cmd": "   "}],
        }}, "non-empty string")

    def test_cmd_combined_with_midi(self):
        assert_clean({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "CMD",  "cmd": "jack_transport start"},
            ],
        }})


class TestJackTransportValidation:

    def test_jack_transport_locate_valid(self):
        assert_clean({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
        }})

    def test_jack_transport_locate_nonzero(self):
        assert_clean({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 48000"}],
        }})

    def test_jack_transport_start_valid(self):
        assert_clean({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "start"}],
        }})

    def test_jack_transport_stop_valid(self):
        assert_clean({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "stop"}],
        }})

    def test_jack_transport_missing_transport_key(self):
        assert_error({"default": {
            "PC5": [{"send": "JACK_TRANSPORT"}],
        }}, "missing required 'transport' key")

    def test_jack_transport_empty_string(self):
        assert_error({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": ""}],
        }}, "missing required 'transport' key")

    def test_jack_transport_invalid_command(self):
        assert_error({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "rewind"}],
        }}, "'start', 'stop', or 'locate <frame>'")

    def test_jack_transport_locate_missing_frame(self):
        assert_error({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate"}],
        }}, "'start', 'stop', or 'locate <frame>'")

    def test_jack_transport_locate_negative_frame(self):
        assert_error({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate -1"}],
        }}, "'start', 'stop', or 'locate <frame>'")

    def test_jack_transport_locate_nonnumeric_frame(self):
        assert_error({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate start"}],
        }}, "'start', 'stop', or 'locate <frame>'")

    def test_jack_transport_combined_with_midi(self):
        assert_clean({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "JACK_TRANSPORT", "transport": "locate 0"},
            ],
        }})

    def test_jack_transport_not_flagged_as_unrecognised(self):
        """JACK_TRANSPORT must not trigger the unrecognised-send error."""
        assert_clean({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "stop"}],
        }})


class TestRepeatAccelValidation:

    def test_valid_single_tier_repeat_only(self):
        assert_clean({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 150,
                "repeat_accel": [
                    {"after_ms": 2000, "repeat": [{"send": "CC10", "value": 5}]},
                ],
            },
        }})

    def test_valid_repeat_ms_only_tier(self):
        assert_clean({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 200,
                "repeat_accel": [
                    {"after_ms": 1000, "repeat_ms": 80},
                ],
            },
        }})

    def test_valid_both_keys_in_tier(self):
        assert_clean({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 200,
                "repeat_accel": [
                    {"after_ms": 1000,
                     "repeat": [{"send": "CC10", "value": 3}],
                     "repeat_ms": 80},
                ],
            },
        }})

    def test_valid_multiple_tiers(self):
        assert_clean({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 200,
                "repeat_accel": [
                    {"after_ms": 1000, "repeat": [{"send": "CC10", "value": 2}]},
                    {"after_ms": 3000, "repeat": [{"send": "CC10", "value": 5}],
                     "repeat_ms": 100},
                ],
            },
        }})

    def test_requires_repeat_at_top_level(self):
        assert_error({"default": {
            "CC3": {
                "single":    [{"send": "CC10", "value": 1}],
                "repeat_accel": [
                    {"after_ms": 1000, "repeat": [{"send": "CC10", "value": 5}]},
                ],
            },
        }}, "requires 'repeat' at the top level")

    def test_must_be_a_list(self):
        assert_error({"default": {
            "CC3": {
                "repeat":       [{"send": "CC10", "value": 1}],
                "repeat_accel": "not-a-list",
            },
        }}, "must be a list")

    def test_tier_missing_after_ms(self):
        assert_error({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_accel": [
                    {"repeat": [{"send": "CC10", "value": 5}]},
                ],
            },
        }}, "missing required 'after_ms'")

    def test_tier_after_ms_not_positive(self):
        assert_error({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_accel": [
                    {"after_ms": -1, "repeat": [{"send": "CC10", "value": 5}]},
                ],
            },
        }}, "'after_ms' must be a positive number")

    def test_tier_missing_both_repeat_and_repeat_ms(self):
        assert_error({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_accel": [
                    {"after_ms": 1000},
                ],
            },
        }}, "at least one of 'repeat' or 'repeat_ms'")

    def test_tier_repeat_ms_not_positive(self):
        assert_error({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_accel": [
                    {"after_ms": 1000, "repeat_ms": 0},
                ],
            },
        }}, "'repeat_ms' must be a positive number")

    def test_tier_repeat_sequence_validated(self):
        """Sequences inside tiers go through the same check_sequence logic."""
        assert_error({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_accel": [
                    {"after_ms": 1000,
                     "repeat": [{"send": "CC999_BAD"}]},
                ],
            },
        }}, "CC999_BAD")


class TestOscValidation:

    def test_valid_basic(self):
        assert_clean({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/test"}],
        }})

    def test_valid_with_args(self):
        assert_clean({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/v", "args": [1, 0.5, "x"]}],
        }})

    def test_valid_empty_args(self):
        assert_clean({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/ping", "args": []}],
        }})

    def test_valid_port_boundaries(self):
        assert_clean({"default": {
            "PC5": [{"send": "OSC", "host": "h", "port": 1,
                     "address": "/a"}],
        }})
        assert_clean({"default": {
            "PC5": [{"send": "OSC", "host": "h", "port": 65535,
                     "address": "/a"}],
        }})

    def test_missing_host(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "port": 9000, "address": "/a"}],
        }}, "missing required 'host'")

    def test_empty_host(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "", "port": 9000, "address": "/a"}],
        }}, "missing required 'host'")

    def test_missing_port(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "address": "/a"}],
        }}, "missing required 'port'")

    def test_port_zero(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 0,
                     "address": "/a"}],
        }}, "1-65535")

    def test_port_too_high(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 65536,
                     "address": "/a"}],
        }}, "1-65535")

    def test_port_is_string(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": "9000",
                     "address": "/a"}],
        }}, "1-65535")

    def test_port_is_float(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000.0,
                     "address": "/a"}],
        }}, "1-65535")

    def test_port_is_bool(self):
        # bool is a subclass of int; must be explicitly rejected
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": True,
                     "address": "/a"}],
        }}, "1-65535")

    def test_missing_address(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000}],
        }}, "starting with '/'")

    def test_address_no_leading_slash(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "no-slash"}],
        }}, "starting with '/'")

    def test_address_not_a_string(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": 42}],
        }}, "starting with '/'")

    def test_args_not_a_list(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/a", "args": 42}],
        }}, "must be a list")

    def test_args_element_is_dict(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/a", "args": [{}]}],
        }}, "int, float, or str")

    def test_args_element_is_bool(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/a", "args": [True]}],
        }}, "int, float, or str")

    def test_args_element_is_none(self):
        assert_error({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/a", "args": [None]}],
        }}, "int, float, or str")

    def test_multiple_errors_reported(self):
        """All three field errors are reported, not just the first."""
        errs = errors_for({"default": {
            "PC5": [{"send": "OSC"}],   # missing host, port, address
        }})
        texts = " ".join(errs)
        assert "host" in texts
        assert "port" in texts
        assert "'/'" in texts

    def test_not_flagged_as_unrecognised(self):
        assert_clean({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/ok"}],
        }})

    def test_combined_with_midi_and_jack_transport(self):
        assert_clean({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "OSC",  "host": "127.0.0.1", "port": 9000,
                 "address": "/trigger"},
                {"send": "JACK_TRANSPORT", "transport": "locate 0"},
            ],
        }})


# ---------------------------------------------------------------------------
# Channel override validation
# ---------------------------------------------------------------------------

class TestChannelValidation:
    """'channel' key on CC/PC/NOTE sends: range and type checks."""

    def test_valid_channel_on_cc(self):
        assert_clean({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 2}],
        }})

    def test_valid_channel_on_pc(self):
        assert_clean({"default": {
            "CC5": [{"send": "PC7", "channel": 3}],
        }})

    def test_valid_channel_on_note(self):
        assert_clean({"default": {
            "CC5": [{"send": "NOTE60", "velocity": 64, "channel": 1}],
        }})

    def test_valid_channel_min_boundary(self):
        # data_offset=1 → valid range 1-16
        assert_clean({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 1}],
        }}, data_offset=1)

    def test_valid_channel_max_boundary(self):
        assert_clean({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 16}],
        }}, data_offset=1)

    def test_valid_channel_data_offset_0(self):
        # data_offset=0 → valid range 0-15
        assert_clean({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 0}],
        }}, data_offset=0)

    def test_channel_zero_invalid_with_data_offset_1(self):
        assert_error({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 0}],
        }}, "out of range", data_offset=1)

    def test_channel_17_invalid_with_data_offset_1(self):
        assert_error({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 17}],
        }}, "out of range", data_offset=1)

    def test_channel_not_int(self):
        assert_error({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": "2"}],
        }}, "'channel' must be an integer")

    def test_channel_bool_rejected(self):
        # bool is a subclass of int in Python; must be caught explicitly
        assert_error({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": True}],
        }}, "'channel' must be an integer")

    def test_channel_float_rejected(self):
        assert_error({"default": {
            "CC5": [{"send": "CC10", "value": 127, "channel": 2.0}],
        }}, "'channel' must be an integer")

    def test_channel_on_sysex_ignored(self):
        # SYSEX has no channel field; 'channel' key is harmless but not validated
        assert_clean({"default": {
            "CC5": [{"send": "SYSEX", "sysex": [0xF0, 0x00, 0xF7],
                     "channel": 99}],
        }})


# ---------------------------------------------------------------------------
# eager_single validation (§5 of EAGER_SINGLE_PLAN)
# ---------------------------------------------------------------------------

class TestEagerSingleValidation:
    """validate() checks for eager_single misuse (§5.1–§5.4)."""

    # ------------------------------------------------------------------
    # Valid uses → no error, no warning
    # ------------------------------------------------------------------

    def test_valid_with_double(self):
        assert_clean({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})

    def test_valid_with_long(self):
        assert_clean({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "long":   [{"send": "CC11", "value": 2}],
            },
        }})

    def test_valid_with_repeat(self):
        assert_clean({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "repeat": [{"send": "CC11", "value": 2}],
            },
        }})

    def test_valid_with_triple(self):
        assert_clean({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "triple": [{"send": "CC11", "value": 2}],
            },
        }})

    def test_false_value_no_error(self):
        """eager_single: False is valid (just a no-op)."""
        assert_clean({"default": {
            "CC5": {
                "eager_single": False,
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})

    # ------------------------------------------------------------------
    # §5.1 — only-single entry → warning, not error
    # ------------------------------------------------------------------

    def test_only_single_produces_warning(self):
        """eager_single with no deferred labels → warning."""
        warns = warnings_for({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        assert any("flag has no effect" in w for w in warns)

    def test_only_single_no_error(self):
        """eager_single with no deferred labels → no error (still valid config)."""
        assert errors_for({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
            },
        }}) == []

    # ------------------------------------------------------------------
    # §5.2 — no 'single' action → hard error
    # ------------------------------------------------------------------

    def test_no_single_action_is_error(self):
        assert_error({"default": {
            "CC5": {
                "eager_single": True,
                "double": [{"send": "CC11", "value": 2}],
            },
        }}, "no 'single' action is defined")

    # ------------------------------------------------------------------
    # §5.3 — non-bool value → hard error
    # ------------------------------------------------------------------

    def test_non_bool_int_is_error(self):
        assert_error({"default": {
            "CC5": {
                "eager_single": 1,
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }}, "must be True or False")

    def test_non_bool_string_is_error(self):
        assert_error({"default": {
            "CC5": {
                "eager_single": "yes",
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }}, "must be True or False")

    # ------------------------------------------------------------------
    # §5.4 — BANK send inside eager single → hard error
    # ------------------------------------------------------------------

    def test_bank_in_eager_single_is_error(self):
        assert_error({
            "default": {
                "CC5": {
                    "eager_single": True,
                    "single": [{"send": "BANK", "bank": "other"}],
                    "double": [{"send": "CC11", "value": 2}],
                },
            },
            "other": {},
        }, "'BANK' send is not allowed")

    def test_bank_in_eager_single_mentions_mid_gesture(self):
        """Error message explains why BANK is forbidden."""
        errs = errors_for({
            "default": {
                "CC5": {
                    "eager_single": True,
                    "single": [{"send": "BANK", "bank": "other"}],
                    "double": [{"send": "CC11", "value": 2}],
                },
            },
            "other": {},
        })
        assert any("wrong bank" in e for e in errs)

    def test_bank_in_non_eager_single_is_ok(self):
        """BANK inside a non-eager single is still perfectly valid."""
        assert_clean({
            "default": {
                "CC5": [{"send": "BANK", "bank": "other"}],
            },
            "other": {},
        })
