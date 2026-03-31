"""
test_bankset.py

Tests for BankSet event-handling behaviour: direct mappings, toggles,
long press, multi-press, chords, and bank switching.
"""
import time
import pytest
from conftest import make_bankset, make_pc, make_cc, make_note


# ---------------------------------------------------------------------------
# Direct mappings
# ---------------------------------------------------------------------------

class TestDirect:

    def test_single_output_returned(self):
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 64}],
        }})
        result = bs.handle(make_pc(5))
        assert len(result) == 1
        assert result[0].kind  == "CC"
        assert result[0].ctrl  == 10
        assert result[0].value == 64

    def test_multiple_outputs_all_returned(self):
        bs, out = make_bankset({"default": {
            "PC5": [
                {"send": "NOTE36", "velocity": 100},
                {"send": "CC10",   "value": 64},
            ],
        }})
        result = bs.handle(make_pc(5))
        assert len(result) == 2
        assert result[0].kind     == "NOTEON"
        assert result[0].note     == 36
        assert result[0].velocity == 100
        assert result[1].kind     == "CC"
        assert result[1].ctrl     == 10

    def test_unmapped_key_returns_none(self):
        bs, out = make_bankset({"default": {}})
        assert bs.handle(make_pc(5)) is None

    def test_delayed_output_goes_via_output_fn(self, fake_timer):
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.1}],
        }})
        result = bs.handle(make_pc(5))
        assert result is None          # nothing immediate
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].kind == "CC"


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

class TestToggle:

    def _make(self, debounce_ms=0):
        return make_bankset(
            {"default": {
                "CC22": {
                    "a": [{"send": "CC40", "value": 127}],
                    "b": [{"send": "CC40", "value": 0}],
                },
            }},
            debounce_ms=debounce_ms,
        )

    def test_first_press_gives_state_a(self):
        bs, _ = self._make()
        result = bs.handle(make_cc(22))
        assert result[0].value == 127

    def test_second_press_gives_state_b(self):
        bs, _ = self._make()
        bs.handle(make_cc(22))
        result = bs.handle(make_cc(22))
        assert result[0].value == 0

    def test_alternates_aba(self):
        bs, _ = self._make()
        values = [bs.handle(make_cc(22))[0].value for _ in range(4)]
        assert values == [127, 0, 127, 0]

    def test_debounce_suppresses_rapid_repeat(self):
        bs, _ = self._make(debounce_ms=200)
        bs.handle(make_cc(22))         # fires
        result = bs.handle(make_cc(22))  # too soon
        assert result is None

    def test_state_persists_across_bank_switch(self):
        bs, _ = make_bankset({
            "default": {
                "CC22": {
                    "a": [{"send": "CC40", "value": 127}],
                    "b": [{"send": "CC40", "value": 0}],
                },
            },
            "other": {},
        })
        bs.handle(make_cc(22))    # now in state a
        bs.switch_bank("other")
        bs.switch_bank("default")
        result = bs.handle(make_cc(22))   # should continue from state a -> b
        assert result[0].value == 0


# ---------------------------------------------------------------------------
# Long press
# ---------------------------------------------------------------------------

class TestLongPress:

    def _make(self, long_press_ms=200):
        return make_bankset(
            {"default": {
                "CC30": {
                    "tap":  [{"send": "PC1"}],
                    "long": [{"send": "PC2"}],
                },
            }},
            long_press_ms=long_press_ms,
        )

    def test_quick_release_gives_tap(self):
        bs, _ = self._make(long_press_ms=300)
        bs.handle(make_cc(30, value=127))          # press
        time.sleep(0.05)
        result = bs.handle(make_cc(30, value=0))   # quick release
        assert result[0].kind    == "PC"
        assert result[0].program == 1

    def test_slow_release_gives_long(self):
        bs, _ = self._make(long_press_ms=50)
        bs.handle(make_cc(30, value=127))          # press
        time.sleep(0.1)
        result = bs.handle(make_cc(30, value=0))   # slow release
        assert result[0].kind    == "PC"
        assert result[0].program == 2

    def test_release_without_press_returns_none(self):
        bs, _ = self._make()
        result = bs.handle(make_cc(30, value=0))
        assert result is None

    def test_per_key_long_ms_override(self):
        bs, _ = make_bankset({"default": {
            "CC30": {
                "tap":     [{"send": "PC1"}],
                "long":    [{"send": "PC2"}],
                "long_ms": 50,
            },
        }})
        bs.handle(make_cc(30, value=127))
        time.sleep(0.1)
        result = bs.handle(make_cc(30, value=0))
        assert result[0].program == 2


# ---------------------------------------------------------------------------
# Multi-press
# ---------------------------------------------------------------------------

class TestMultiPress:

    def _make(self):
        return make_bankset({"default": {
            "PC4": {
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
                "triple": [{"send": "CC12", "value": 3}],
            },
        }})

    def test_single_press_fires_single(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 10

    def test_double_press_fires_double(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        bs.handle(make_pc(4))
        # First timer should be cancelled, only last active
        active = fake_timer.active()
        assert len(active) == 1
        active[0].fire()
        assert out[0].ctrl == 11

    def test_triple_press_fires_triple(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        bs.handle(make_pc(4))
        bs.handle(make_pc(4))
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 12

    def test_unmapped_count_fires_nothing(self, fake_timer):
        bs, out = self._make()
        for _ in range(4):
            bs.handle(make_pc(4))
        fake_timer.active()[0].fire()
        assert out == []


# ---------------------------------------------------------------------------
# Chord
# ---------------------------------------------------------------------------

class TestChord:

    def _make(self):
        return make_bankset({"default": {
            "PC5": [{"send": "CC50", "value": 1}],   # individual entry
            ("PC4", "PC5"): {
                "single": [{"send": "CC99", "value": 127}],
            },
        }})

    def test_chord_fires_when_complete(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        bs.handle(make_pc(5))   # completes chord before window expires
        assert len(out) == 1
        assert out[0].ctrl == 99

    def test_chord_timer_cancelled_on_completion(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        bs.handle(make_pc(5))
        # All timers should be cancelled after completion
        assert all(t.cancelled for t in fake_timer.instances)

    def test_incomplete_chord_fallback_fires_individual(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(5))   # PC5 has an individual entry
        # Window expires without PC4
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        # Should have dispatched PC5's individual mapping
        assert len(out) == 1
        assert out[0].ctrl == 50

    def test_incomplete_chord_unmapped_key_passed_through(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))   # PC4 has no individual entry
        fake_timer.active()[0].fire()
        # Unmapped key should be passed through via output_fn
        assert len(out) == 1
        # The passed-through event is the original FakeInputEvent
        assert out[0].program == 4


# ---------------------------------------------------------------------------
# Bank switching
# ---------------------------------------------------------------------------

class TestBankSwitch:

    def test_bank_send_switches_active_bank(self):
        bs, _ = make_bankset({
            "default": {
                "PC1": [{"send": "BANK", "bank": "other"}],
            },
            "other": {},
        })
        assert bs.active_bank == "default"
        bs.handle(make_pc(1))
        assert bs.active_bank == "other"

    def test_new_bank_mapping_active_after_switch(self):
        bs, _ = make_bankset({
            "default": {
                "PC1": [{"send": "BANK", "bank": "other"}],
                "PC2": [{"send": "CC10", "value": 1}],
            },
            "other": {
                "PC2": [{"send": "CC20", "value": 2}],
            },
        })
        bs.handle(make_pc(1))
        result = bs.handle(make_pc(2))
        assert result[0].ctrl == 20

    def test_switch_to_unknown_bank_raises(self):
        bs, _ = make_bankset({"default": {}})
        with pytest.raises(ValueError, match="unknown bank"):
            bs.switch_bank("nonexistent")
