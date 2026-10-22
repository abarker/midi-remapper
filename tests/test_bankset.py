"""
test_bankset.py

Tests for BankSet event-handling behavior: direct mappings, toggles,
gestures (single/double/triple/long), chords, and bank switching.
"""
import time
import pytest
from conftest import make_bankset, make_pc, make_cc, make_note, make_noteoff


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

    def test_empty_sequence_drops_event(self):
        bs, out = make_bankset({"default": {
            "PC5": [],
        }})
        result = bs.handle(make_pc(5))
        assert result == []

    def test_delayed_output_goes_via_output_fn(self, fake_timer):
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.1}],
        }})
        result = bs.handle(make_pc(5))
        assert result == []            # nothing immediate, event handled
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].kind == "CC"

    def test_cc_release_remapped_for_direct(self):
        # Direct CC mappings should remap both press and release.
        bs, out = make_bankset({"default": {
            "CC0": [{"send": "CC4"}],
        }})
        bs.handle(make_cc(0, value=127))
        result = bs.handle(make_cc(0, value=0))
        assert result is not None
        assert result[0].value == 0

    def test_press_only_suppresses_release(self):
        bs, out = make_bankset({"default": {
            "CC0": [{"send": "CC4", "press_only": True}],
        }})
        bs.handle(make_cc(0, value=127))
        result = bs.handle(make_cc(0, value=0))
        # Release should be remapped but press_only skips the item -> []
        assert result == []


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
        result = bs.handle(make_cc(22))   # should continue from a -> b
        assert result[0].value == 0

    def test_release_suppressed_for_toggle(self):
        bs, _ = self._make()
        bs.handle(make_cc(22, value=127))
        result = bs.handle(make_cc(22, value=0))
        assert result == []


# ---------------------------------------------------------------------------
# Gesture: single only (immediate, no timing)
# ---------------------------------------------------------------------------

class TestGestureSingleOnly:

    def test_single_fires_immediately(self):
        bs, out = make_bankset({"default": {
            "CC0": {"single": [{"send": "CC10", "value": 1}]},
        }})
        result = bs.handle(make_cc(0))
        assert result is not None
        assert len(result) == 1
        assert result[0].ctrl == 10

    def test_release_suppressed(self):
        bs, out = make_bankset({"default": {
            "CC0": {"single": [{"send": "CC10", "value": 1}]},
        }})
        bs.handle(make_cc(0, value=127))
        result = bs.handle(make_cc(0, value=0))
        assert result == []


# ---------------------------------------------------------------------------
# Gesture: long press (single + long)
# ---------------------------------------------------------------------------

class TestGestureLong:

    def _make(self, long_press_ms=200):
        return make_bankset(
            {"default": {
                "CC30": {
                    "single": [{"send": "PC1"}],
                    "long":   [{"send": "PC2"}],
                },
            }},
            long_press_ms=long_press_ms,
        )

    def test_press_suppressed(self, fake_timer):
        bs, _ = self._make()
        result = bs.handle(make_cc(30, value=127))
        assert result == []

    def test_quick_release_gives_single(self, fake_timer):
        # Quick release: long timer canceled, single fires via return value.
        bs, _ = self._make(long_press_ms=300)
        bs.handle(make_cc(30, value=127))
        result = bs.handle(make_cc(30, value=0))
        assert result[0].kind    == "PC"
        assert result[0].program == 1

    def test_long_fires_via_timer_before_release(self, fake_timer):
        # Long fires immediately when threshold timer expires, no waiting.
        bs, out = self._make()
        bs.handle(make_cc(30, value=127))
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].kind    == "PC"
        assert out[0].program == 2

    def test_release_suppressed_after_long_fires(self, fake_timer):
        # After the long timer fires, the release is suppressed.
        bs, out = self._make()
        bs.handle(make_cc(30, value=127))
        fake_timer.active()[0].fire()
        result = bs.handle(make_cc(30, value=0))
        assert result == []
        assert len(out) == 1   # only the long event, nothing extra

    def test_release_without_press_returns_none(self, fake_timer):
        bs, _ = self._make()
        result = bs.handle(make_cc(30, value=0))
        assert result is None

    def test_per_key_long_ms_override(self, fake_timer):
        bs, out = make_bankset({"default": {
            "CC30": {
                "single":  [{"send": "PC1"}],
                "long":    [{"send": "PC2"}],
                "long_ms": 50,
            },
        }})
        bs.handle(make_cc(30, value=127))
        fake_timer.active()[0].fire()
        assert out[0].program == 2

    def test_note_gesture_quick_release(self, fake_timer):
        bs, _ = make_bankset(
            {"default": {
                "NOTE60": {
                    "single": [{"send": "CC10", "value": 127}],
                    "long":   [{"send": "CC11", "value": 127}],
                },
            }},
            long_press_ms=300,
        )
        bs.handle(make_note(60))
        result = bs.handle(make_noteoff(60))
        assert result[0].ctrl == 10

    def test_note_gesture_long_fires_via_timer(self, fake_timer):
        bs, out = make_bankset(
            {"default": {
                "NOTE60": {
                    "single": [{"send": "CC10", "value": 127}],
                    "long":   [{"send": "CC11", "value": 127}],
                },
            }},
            long_press_ms=50,
        )
        bs.handle(make_note(60))
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 11


# ---------------------------------------------------------------------------
# Gesture: multi-press (single/double/triple)
# ---------------------------------------------------------------------------

class TestGestureMulti:

    def _make(self):
        return make_bankset({"default": {
            "PC4": {
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
                "triple": [{"send": "CC12", "value": 3}],
            },
        }})

    def test_press_suppressed(self, fake_timer):
        bs, out = self._make()
        result = bs.handle(make_pc(4))
        assert result == []

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

    def test_multi_ms_per_key_override(self, fake_timer):
        # multi_ms overrides the global MULTI_PRESS_WINDOW_MS for this key.
        bs, out = make_bankset({"default": {
            "PC4": {
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
                "multi_ms": 150,
            },
        }}, multi_press_window_ms=300)
        bs.handle(make_pc(4))
        # The timer delay should use 150ms not 300ms.
        assert len(fake_timer.active()) == 1
        assert fake_timer.active()[0].delay == 0.15
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 10


# ---------------------------------------------------------------------------
# Gesture: combined long + multi
# ---------------------------------------------------------------------------

class TestGestureCombined:

    def _make(self, long_press_ms=50):
        return make_bankset(
            {"default": {
                "CC0": {
                    "single": [{"send": "CC10", "value": 1}],
                    "double": [{"send": "CC11", "value": 2}],
                    "long":   [{"send": "CC12", "value": 3}],
                },
            }},
            long_press_ms=long_press_ms,
        )

    def test_long_hold_cancels_multipress_timer(self, fake_timer):
        bs, out = self._make(long_press_ms=50)
        bs.handle(make_cc(0, value=127))
        # Fire the long threshold timer -- long fires immediately.
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 12
        # No pending multipress timer for CC0.
        assert "CC0" not in bs._gesture_timers

    def test_quick_release_lets_multipress_timer_run(self, fake_timer):
        bs, out = self._make(long_press_ms=300)
        bs.handle(make_cc(0, value=127))
        time.sleep(0.01)
        bs.handle(make_cc(0, value=0))   # quick release -- timer starts here
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        # Single press count -> fires 'single'
        assert out[0].ctrl == 10


# ---------------------------------------------------------------------------
# Gesture: hold-repeat
# ---------------------------------------------------------------------------

class TestGestureRepeat:

    def _make(self, repeat_delay_ms=200, repeat_ms=100):
        return make_bankset(
            {"default": {
                "CC0": {
                    "repeat": [{"send": "CC10", "value": 127}],
                },
            }},
            long_press_ms   = 500,
        )

    def _make_with_single(self, repeat_delay_ms=200, repeat_ms=100):
        return make_bankset(
            {"default": {
                "CC0": {
                    "single": [{"send": "CC20", "value": 127}],
                    "repeat": [{"send": "CC10", "value": 127}],
                    "repeat_delay_ms": repeat_delay_ms,
                    "repeat_ms":       repeat_ms,
                },
            }},
        )

    def test_press_suppressed(self, fake_timer):
        bs, out = self._make()
        result = bs.handle(make_cc(0, value=127))
        assert result == []

    def test_first_repeat_fires_after_delay(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(0, value=127))
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 10

    def test_repeat_reschedules_itself(self, fake_timer):
        # After first repeat fires, a new timer should be scheduled.
        bs, out = self._make()
        bs.handle(make_cc(0, value=127))
        first_timer = fake_timer.active()[0]
        first_timer.fire()
        assert len(out) == 1
        # A new repeat timer should now be pending in the BankSet state.
        assert "CC0" in bs._gesture_repeat_timers
        assert not bs._gesture_repeat_timers["CC0"].canceled

    def test_second_repeat_fires(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(0, value=127))
        fake_timer.active()[0].fire()  # first repeat
        fake_timer.active()[0].fire()  # second repeat
        assert len(out) == 2
        assert all(e.ctrl == 10 for e in out)

    def test_release_cancels_repeat(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(0, value=127))
        first = fake_timer.active()[0]
        first.fire()                        # first repeat fires
        bs.handle(make_cc(0, value=0))      # release
        # The rescheduled repeat timer should be canceled.
        assert "CC0" not in bs._gesture_repeat_timers
        assert len(out) == 1  # only the one repeat that already fired

    def test_quick_release_before_first_repeat_fires_single(self, fake_timer):
        # Release before any repeat fires -- treated as quick tap.
        bs, out = self._make_with_single(repeat_delay_ms=500)
        bs.handle(make_cc(0, value=127))
        result = bs.handle(make_cc(0, value=0))   # quick release
        # 'single' fires via return value.
        assert result is not None
        assert len(result) == 1
        assert result[0].ctrl == 20

    def test_release_after_repeat_fires_nothing(self, fake_timer):
        # Hold long enough for repeat to fire, then release -- no extra output.
        bs, out = self._make_with_single()
        bs.handle(make_cc(0, value=127))
        fake_timer.active()[0].fire()      # repeat fires
        result = bs.handle(make_cc(0, value=0))
        # Repeat already fired, so release is silent.
        assert result == []
        assert len(out) == 1  # only the repeat event

    def test_repeat_delay_ms_per_key_override(self, fake_timer):
        bs, out = make_bankset({"default": {
            "CC0": {
                "repeat":           [{"send": "CC10", "value": 127}],
                "repeat_delay_ms":  50,
                "repeat_ms":        25,
            },
        }})
        bs.handle(make_cc(0, value=127))
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 10

    def test_repeat_with_double(self, fake_timer):
        # Double tap should still work alongside repeat.
        bs, out = make_bankset({"default": {
            "CC0": {
                "single": [{"send": "CC10", "value": 127}],
                "double": [{"send": "CC11", "value": 127}],
                "repeat": [{"send": "CC12", "value": 127}],
                "repeat_delay_ms": 300,
            },
        }})
        # First press + quick release (no repeat fires) -> single pending
        bs.handle(make_cc(0, value=127))
        bs.handle(make_cc(0, value=0))
        assert bs._gesture_counts.get("CC0") == 1

        # Second press + quick release -> count = 2
        bs.handle(make_cc(0, value=127))
        bs.handle(make_cc(0, value=0))
        assert bs._gesture_counts.get("CC0") == 2

        # Multipress window expires -> double fires
        multi_timer = bs._gesture_timers.get("CC0")
        assert multi_timer is not None
        multi_timer.fire()
        assert len(out) == 1
        assert out[0].ctrl == 11


# ---------------------------------------------------------------------------
# Trigger value
# ---------------------------------------------------------------------------

class TestTriggerValue:

    def test_exact_match_fires(self):
        bs, out = make_bankset({"default": {
            "CC0": {
                "trigger_value": 127,
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        result = bs.handle(make_cc(0, value=127))
        assert result is not None and len(result) == 1

    def test_exact_mismatch_passes_through(self):
        bs, out = make_bankset({"default": {
            "CC0": {
                "trigger_value": 64,
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        result = bs.handle(make_cc(0, value=127))
        assert result is None

    def test_range_match(self):
        bs, out = make_bankset({"default": {
            "CC0": {
                "trigger_value": "64-127",
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        assert bs.handle(make_cc(0, value=100)) is not None
        assert bs.handle(make_cc(0, value=63))  is None

    def test_greater_than(self):
        bs, out = make_bankset({"default": {
            "CC0": {
                "trigger_value": ">64",
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        assert bs.handle(make_cc(0, value=65))  is not None
        assert bs.handle(make_cc(0, value=64))  is None

    def test_list_spec(self):
        bs, out = make_bankset({"default": {
            "CC0": {
                "trigger_value": [1, "64-127"],
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        assert bs.handle(make_cc(0, value=1))   is not None
        assert bs.handle(make_cc(0, value=100)) is not None
        assert bs.handle(make_cc(0, value=32))  is None


# ---------------------------------------------------------------------------
# Chord
# ---------------------------------------------------------------------------

class TestChord:

    def _make(self):
        return make_bankset({"default": {
            "PC5": [{"send": "CC50", "value": 1}],
            ("PC4", "PC5"): {
                "single": [{"send": "CC99", "value": 127}],
            },
        }})

    def test_chord_fires_when_complete(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        result = bs.handle(make_pc(5))
        assert result is not None
        assert len(result) == 1
        assert result[0].ctrl == 99

    def test_chord_bank_switch_via_return_value(self, fake_timer):
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "BANK", "bank": "drums"}],
                },
            },
            "drums": {},
        })
        bs.handle(make_cc(1))
        result = bs.handle(make_cc(2))
        assert result == []
        assert bs.active_bank == "drums"

    def test_chord_press_events_not_passed_through(self, fake_timer):
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "BANK", "bank": "drums"}],
                },
            },
            "drums": {},
        })
        bs.handle(make_cc(1))
        bs.handle(make_cc(2))
        assert out == []

    def test_chord_release_events_suppressed_after_bank_switch(self, fake_timer):
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "BANK", "bank": "drums"}],
                },
            },
            "drums": {
                "CC1": [{"send": "CC10"}],
                "CC2": [{"send": "CC11"}],
            },
        })
        bs.handle(make_cc(1))
        bs.handle(make_cc(2))
        bs.handle(make_cc(1, value=0))
        bs.handle(make_cc(2, value=0))
        assert out == []

    def test_chord_timer_canceled_on_completion(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        bs.handle(make_pc(5))
        assert all(t.canceled for t in fake_timer.instances)

    def test_incomplete_chord_fallback_fires_individual(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(5))
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 50

    def test_incomplete_chord_unmapped_key_passed_through(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].program == 4

    def test_overlapping_chords_no_spurious_fallback(self, fake_timer):
        # When two chords share a key and one completes, the other window
        # should be canceled without dispatching any fallback.
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {"single": [{"send": "BANK", "bank": "drums"}]},
                ("CC2", "CC3"): {"single": [{"send": "CC99", "value": 127}]},
                "CC2": [{"send": "CC50", "press_only": True}],
            },
            "drums": {},
        })
        bs.handle(make_cc(2, value=127))  # opens windows for both chords
        bs.handle(make_cc(1, value=127))  # completes ("CC1","CC2")
        # ("CC2","CC3") window should be canceled, no fallback
        for t in fake_timer.active():
            t.fire()
        assert out == []
        assert bs.active_bank == "drums"

    def test_overlapping_chords_no_double_fallback_on_expiry(self, fake_timer):
        # When two chord windows sharing a key both expire, the shared key
        # should only be dispatched once, not twice.
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {"single": [{"send": "CC98", "value": 127}]},
                ("CC2", "CC3"): {"single": [{"send": "CC99", "value": 127}]},
                "CC2": [{"send": "CC50", "press_only": True}],
            },
        })
        bs.handle(make_cc(2, value=127))  # opens both windows
        # Both windows expire without completing
        for t in list(fake_timer.active()):
            t.fire()
        # CC2 should be dispatched exactly once
        cc50_events = [e for e in out if hasattr(e, 'ctrl') and e.ctrl == 50]
        assert len(cc50_events) == 1
        bs, out = make_bankset({
            "default": {
                "CC1": [{"send": "CC10"}],
                ("CC1", "CC2"): {
                    "single": [{"send": "CC99", "value": 127}],
                },
            },
        })
        bs.handle(make_cc(1))
        result = bs.handle(make_cc(1, value=0))
        assert result is not None
        assert out == []


# ---------------------------------------------------------------------------
# Gesture inside fast chord
# ---------------------------------------------------------------------------

class TestGestureInsideFastChord:
    """
    Tests for gesture keys that are also members of a fast chord.
    The fast chord dismissal on release must complete the full
    press+release cycle for the gesture so that long/multi work correctly.
    """

    def _make(self):
        return make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "BANK", "bank": "drums"}],
                },
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "double": [{"send": "CC11", "value": 127}],
                    "triple": [{"send": "CC22", "value": 127}],
                    "long":   [{"send": "PC88"}],
                    "long_ms": 300,
                },
            },
            "drums": {},
        }, long_press_ms=300)

    def test_single_tap_fires_via_timer(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(1, value=127))   # chord window opens
        bs.handle(make_cc(1, value=0))     # fast chord dismissed, gesture press+release handled
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 10

    def test_double_tap_fires_via_timer(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(1, value=127))
        bs.handle(make_cc(1, value=0))     # first tap -- timer starts
        bs.handle(make_cc(1, value=127))
        bs.handle(make_cc(1, value=0))     # second tap -- timer resets
        active = fake_timer.active()
        assert len(active) == 1
        active[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 11

    def test_long_press_fires_via_timer(self, fake_timer):
        # Long press: chord window expires (standard fallback), gesture press
        # recorded, then long-press threshold timer fires immediately.
        bs, out = self._make()
        bs.handle(make_cc(1, value=127))
        # Only chord window timer at press time.
        assert len(fake_timer.active()) == 1
        chord_timer = fake_timer.active()[0]
        chord_timer.fire()   # chord expires, fallback records gesture press
        # Long threshold timer now exists (plus possibly new chord window
        # for repeat attempts -- fire only the long timer).
        long_timer = bs._gesture_long_timers.get("CC1")
        assert long_timer is not None
        long_timer.fire()   # long fires
        assert len(out) == 1
        assert out[0].kind    == "PC"
        assert out[0].program == 88

    def test_chord_still_fires_when_both_keys_arrive(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(1, value=127))
        result = bs.handle(make_cc(2, value=127))   # chord completes
        assert result == []
        assert bs.active_bank == "drums"

    def test_chord_releases_suppressed_after_switch(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(1, value=127))
        bs.handle(make_cc(2, value=127))
        bs.handle(make_cc(1, value=0))
        bs.handle(make_cc(2, value=0))
        assert out == []


# ---------------------------------------------------------------------------
# Chord multi-press
# ---------------------------------------------------------------------------

class TestChordMultiPress:

    def _make(self):
        return make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "CC10", "value": 127}],
                    "double": [{"send": "CC11", "value": 127}],
                    "triple": [{"send": "CC12", "value": 127}],
                },
            },
        })

    def _complete_chord(self, bs):
        bs.handle(make_cc(1, value=127))
        bs.handle(make_cc(2, value=127))

    def test_single_chord_fires_via_timer(self, fake_timer):
        bs, out = self._make()
        self._complete_chord(bs)
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 10

    def test_double_chord_fires_via_timer(self, fake_timer):
        bs, out = self._make()
        self._complete_chord(bs)
        self._complete_chord(bs)
        active = fake_timer.active()
        assert len(active) == 1
        active[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 11

    def test_triple_chord_fires_via_timer(self, fake_timer):
        bs, out = self._make()
        self._complete_chord(bs)
        self._complete_chord(bs)
        self._complete_chord(bs)
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 12

    def test_unmapped_count_fires_nothing(self, fake_timer):
        bs, out = self._make()
        for _ in range(4):
            self._complete_chord(bs)
        fake_timer.active()[0].fire()
        assert out == []

    def test_single_only_chord_fires_immediately(self, fake_timer):
        # Chord with only "single" and no double/triple: fires immediately
        # via handle() return value, no multipress timer needed.
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "CC10", "value": 127}],
                },
            },
        })
        bs.handle(make_cc(1, value=127))
        result = bs.handle(make_cc(2, value=127))
        assert result is not None
        assert result[0].ctrl == 10
        assert len(fake_timer.active()) == 0

    def test_chord_double_bank_switch(self, fake_timer):
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "BANK", "bank": "drums"}],
                    "double": [{"send": "BANK", "bank": "ardour"}],
                },
            },
            "drums":  {},
            "ardour": {},
        })
        self._complete_chord(bs)
        self._complete_chord(bs)
        fake_timer.active()[0].fire()
        assert bs.active_bank == "ardour"


# ---------------------------------------------------------------------------
# CMD send
# ---------------------------------------------------------------------------

class TestCmdSend:
    """Tests for the CMD send type (shell command execution)."""

    def test_cmd_runs_on_direct_mapping(self, fake_timer):
        # CMD fires a subprocess thread; we can verify it doesn't raise
        # and that the MIDI callback returns normally.
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CMD", "cmd": "true"}],
        }})
        result = bs.handle(make_pc(5))
        # CMD items don't produce MIDI output -- result should be []
        assert result == []

    def test_cmd_runs_non_blocking(self, fake_timer):
        # A slow command should not block; the handler returns immediately.
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CMD", "cmd": "sleep 10"}],
        }})
        t0 = time.time()
        bs.handle(make_pc(5))
        elapsed = time.time() - t0
        assert elapsed < 0.5   # must return well before sleep finishes

    def test_cmd_combined_with_midi_send(self, fake_timer):
        # CMD and a MIDI send in the same sequence -- MIDI returns immediately,
        # CMD runs in background.
        bs, out = make_bankset({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "CMD",  "cmd": "true"},
            ],
        }})
        result = bs.handle(make_pc(5))
        assert len(result) == 1
        assert result[0].ctrl == 10

    def test_cmd_with_delay(self, fake_timer):
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CMD", "cmd": "true", "delay": 0.1}],
        }})
        result = bs.handle(make_pc(5))
        assert result == []
        # A timer should have been scheduled for the delayed CMD.
        assert len(fake_timer.active()) == 1

    def test_cmd_in_gesture(self, fake_timer):
        bs, out = make_bankset({"default": {
            "CC0": {
                "single": [
                    {"send": "CC10", "value": 127},
                    {"send": "CMD",  "cmd": "true"},
                ],
                "long": [{"send": "CMD", "cmd": "echo long"}],
            },
        }})
        # long fires via timer
        bs.handle(make_cc(0, value=127))
        fake_timer.active()[0].fire()
        # CMD runs but produces no MIDI output
        assert out == []

    def test_cmd_in_chord(self, fake_timer):
        bs, out = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [
                        {"send": "BANK", "bank": "drums"},
                        {"send": "CMD",  "cmd": "echo switched"},
                    ],
                },
            },
            "drums": {},
        })
        bs.handle(make_cc(1))
        bs.handle(make_cc(2))
        assert bs.active_bank == "drums"


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


class TestGestureReleaseAcrossBankSwitch:
    """A gesture's release goes to the bank that saw its press.

    The rig case (2026-10-22): CC2 (repeat) pressed while CC3's long press
    switched banks; the release arrived in a bank where CC2 is a direct
    mapping, the repeat was never cancelled, and it ran for 12 minutes.
    """

    def _make(self):
        return make_bankset(
            {
                "drums-lst": {
                    "CC2": {
                        "single":          [{"send": "CC1", "value": 127}],
                        "repeat":          [{"send": "CC1", "value": 127}],
                        "repeat_delay_ms": 500,
                        "repeat_ms":       100,
                    },
                    "CC3": {
                        "long":    [{"send": "BANK", "bank": "looper"}],
                        "long_ms": 500,
                    },
                },
                "looper": {
                    "CC2": [{"send": "CC63", "press_only": True}],
                },
            },
            active_bank="drums-lst",
        )

    def _press_cc2_then_switch(self, bs):
        bs.handle(make_cc(3, value=127))
        bs.handle(make_cc(2, value=127))
        bs._gesture_long_timers["CC3"].fire()
        assert bs.active_bank == "looper"

    def test_quick_release_after_switch_stops_repeat(self, fake_timer):
        bs, out = self._make()
        self._press_cc2_then_switch(bs)
        result = bs.handle(make_cc(2, value=0))
        assert "CC2" not in bs._gesture_repeat_timers
        # A quick tap: the pressing bank's single fires once.
        assert [e.ctrl for e in result] == [1]
        for t in fake_timer.active():
            t.fire()
        assert all(e.ctrl != 1 for e in out)

    def test_release_after_switch_stops_running_repeat(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_cc(2, value=127))
        bs._gesture_repeat_timers["CC2"].fire()     # repeat running
        bs.handle(make_cc(3, value=127))
        bs._gesture_long_timers["CC3"].fire()
        assert bs.active_bank == "looper"
        result = bs.handle(make_cc(2, value=0))
        assert result == []
        assert "CC2" not in bs._gesture_repeat_timers
        fired = len(out)
        for t in fake_timer.active():
            t.fire()
        assert len(out) == fired

    def test_release_does_not_fire_new_bank_mapping(self, fake_timer):
        bs, out = self._make()
        self._press_cc2_then_switch(bs)
        result = bs.handle(make_cc(2, value=0))
        assert all(e.ctrl != 63 for e in result + out)

    def test_press_after_switch_uses_new_bank(self, fake_timer):
        bs, out = self._make()
        self._press_cc2_then_switch(bs)
        bs.handle(make_cc(2, value=0))
        result = bs.handle(make_cc(2, value=127))
        assert [e.ctrl for e in result] == [63]
        assert "CC2" not in bs._gesture_repeat_timers


class TestCancelTimersActive:
    """Tests that _active flag prevents zombie timer callbacks after cancel."""

    def test_active_true_on_init(self):
        bs, _ = make_bankset({"default": {}})
        assert bs._active is True

    def test_cancel_timers_sets_active_false(self):
        bs, _ = make_bankset({"default": {}})
        bs.cancel_timers()
        assert bs._active is False

    def test_repeat_does_not_fire_after_cancel(self, fake_timer):
        """Repeat timer that fires after cancel_timers must not reschedule."""
        bs, captured = make_bankset({
            "default": {
                "CC1": {
                    "repeat":          [{"send": "CC10", "value": 127}],
                    "repeat_delay_ms": 200,
                    "repeat_ms":       80,
                },
            }
        })
        bs.handle(make_cc(1, value=127))
        assert len(fake_timer.active()) == 1

        # Simulate: cancel is called while the timer is already executing.
        bs.cancel_timers()
        assert bs._active is False

        # Fire the timer that was "already in flight" at cancel time.
        timer_count_before = len(fake_timer.instances)
        fake_timer.instances[0].fire()

        # No new timer should have been created (repeat did not reschedule).
        assert len(fake_timer.instances) == timer_count_before
        # And nothing should have been output.
        assert captured == []

    def test_long_does_not_fire_after_cancel(self, fake_timer):
        """Long-press timer that fires after cancel_timers must not output."""
        bs, captured = make_bankset({
            "default": {
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "long":   [{"send": "CC20", "value": 127}],
                },
            }
        })
        bs.handle(make_cc(1, value=127))
        long_timer = fake_timer.instances[-1]

        bs.cancel_timers()
        long_timer.fire()   # Simulates the race.

        assert captured == []

    def test_gesture_multipress_does_not_fire_after_cancel(self, fake_timer):
        """Multipress window timer that fires after cancel must not output."""
        bs, captured = make_bankset({
            "default": {
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "double": [{"send": "CC20", "value": 127}],
                },
            }
        })
        bs.handle(make_cc(1, value=127))
        window_timer = fake_timer.instances[-1]

        bs.cancel_timers()
        window_timer.fire()

        assert captured == []

    def test_chord_expire_does_not_dispatch_after_cancel(self, fake_timer):
        """Chord expiry timer that fires after cancel must not dispatch."""
        bs, captured = make_bankset({
            "default": {
                ("CC1", "CC2"): {
                    "single": [{"send": "CC30", "value": 127}],
                },
                "CC1": [{"send": "CC10", "press_only": True}],
            }
        })
        bs.handle(make_cc(1, value=127))   # Open chord window.
        expire_timer = fake_timer.instances[-1]

        bs.cancel_timers()
        expire_timer.fire()   # Expiry fires after cancel.

        # Fallback dispatch of CC1 must not have happened.
        assert captured == []


# ---------------------------------------------------------------------------
# JACK_TRANSPORT send
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_jack_ctrl(monkeypatch):
    """Provide a mock jack_ctrl module so JACK_TRANSPORT tests run without JACK.

    The fixture patches sys.modules so that the lazy import inside
    BankSet._run_jack_transport (``from midi_event_remapper import jack_ctrl``)
    receives the mock rather than trying to open a real JACK connection.
    """
    import sys, types
    calls = []
    mock = types.SimpleNamespace(
        transport_start  = lambda:    calls.append(("start",)),
        transport_stop   = lambda:    calls.append(("stop",)),
        transport_locate = lambda fr: calls.append(("locate", fr)),
        calls            = calls,
    )
    monkeypatch.setitem(sys.modules, "midi_event_remapper.jack_ctrl", mock)
    # Also patch the package attribute: `from midi_event_remapper import
    # jack_ctrl` checks getattr(package, name) before sys.modules, so
    # patching sys.modules alone is not enough once jack_ctrl has been
    # imported as a package attribute by any other module or test file.
    import midi_event_remapper as _mer
    monkeypatch.setattr(_mer, "jack_ctrl", mock, raising=False)
    return mock


class TestJackTransportSend:
    """Tests for the JACK_TRANSPORT send type."""

    def test_locate_runs_non_blocking(self, fake_timer, mock_jack_ctrl):
        """locate must not block the mididings callback."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
        }})
        t0 = time.time()
        result = bs.handle(make_pc(5))
        elapsed = time.time() - t0
        assert result == []          # no MIDI output
        assert elapsed < 0.5        # returns immediately

    def test_locate_calls_transport_locate(self, fake_timer, mock_jack_ctrl):
        """locate <frame> must call jack_ctrl.transport_locate(frame)."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)   # let the daemon thread complete
        assert ("locate", 0) in mock_jack_ctrl.calls

    def test_locate_nonzero_frame(self, fake_timer, mock_jack_ctrl):
        """Frame numbers other than 0 must be forwarded correctly."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 48000"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        assert ("locate", 48000) in mock_jack_ctrl.calls

    def test_start_calls_transport_start(self, fake_timer, mock_jack_ctrl):
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "start"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        assert ("start",) in mock_jack_ctrl.calls

    def test_stop_calls_transport_stop(self, fake_timer, mock_jack_ctrl):
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "stop"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        assert ("stop",) in mock_jack_ctrl.calls

    def test_combined_with_midi_send(self, fake_timer, mock_jack_ctrl):
        """JACK_TRANSPORT in sequence with a MIDI send: MIDI output is returned."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "JACK_TRANSPORT", "transport": "locate 0"},
            ],
        }})
        result = bs.handle(make_pc(5))
        time.sleep(0.05)
        assert len(result) == 1
        assert result[0].ctrl == 10
        assert ("locate", 0) in mock_jack_ctrl.calls

    def test_delayed_jack_transport(self, fake_timer, mock_jack_ctrl):
        """delay schedules a timer, just like CMD."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 0",
                     "delay": 0.1}],
        }})
        result = bs.handle(make_pc(5))
        assert result == []
        assert len(fake_timer.active()) == 1   # timer was scheduled

    def test_jack_transport_in_gesture(self, fake_timer, mock_jack_ctrl):
        """JACK_TRANSPORT works inside a gesture sequence."""
        import time
        bs, out = make_bankset({"default": {
            "CC0": {
                "single": [{"send": "JACK_TRANSPORT", "transport": "stop"}],
                "long":   [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
            },
        }})
        bs.handle(make_cc(0, value=127))
        fake_timer.active()[0].fire()   # long timer fires
        time.sleep(0.05)
        assert ("locate", 0) in mock_jack_ctrl.calls


# ---------------------------------------------------------------------------
# JACK_TRANSPORT stuck-thread detection
# ---------------------------------------------------------------------------

class TestTransportLeakDetection:
    """Verify _cleanup_timers detects a JACK_TRANSPORT thread that never
    returns, mirroring TestDelayLeakDetection for delay-send threads.

    _run_jack_transport spawns a plain threading.Thread (not a
    fake_timer-backed threading.Timer, since transport calls run
    immediately rather than after a scheduled delay), so these tests use
    a real thread blocked on a threading.Event to represent "still
    running", then backdate its recorded start time so the 1s threshold
    is crossed without an actual multi-second sleep in the test suite.
    """

    def test_overdue_transport_thread_prints_warning(self, capsys):
        import threading
        bs, out = make_bankset({"default": {}})
        block = threading.Event()
        t = threading.Thread(target=block.wait, daemon=True)
        t.start()
        # Backdate the recorded start time so it looks like this call has
        # been running for 2s, without actually waiting 2s in the test.
        bs._transport_threads.append((t, time.monotonic() - 2.0, "locate 0"))
        bs._cleanup_timers()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "JACK transport call stuck" in captured.out
        block.set()
        t.join(timeout=1)

    def test_overdue_transport_thread_warned_only_once(self, capsys):
        import threading
        bs, out = make_bankset({"default": {}})
        block = threading.Event()
        t = threading.Thread(target=block.wait, daemon=True)
        t.start()
        bs._transport_threads.append((t, time.monotonic() - 2.0, "locate 0"))
        bs._cleanup_timers()
        capsys.readouterr()              # discard first warning
        bs._cleanup_timers()
        captured = capsys.readouterr()
        assert "WARNING" not in captured.out   # no second warning
        block.set()
        t.join(timeout=1)

    def test_completed_transport_thread_not_warned(self, capsys):
        import threading
        bs, out = make_bankset({"default": {}})
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        t.join(timeout=1)   # ensure it has already finished
        bs._transport_threads.append((t, time.monotonic(), "locate 0"))
        bs._cleanup_timers()
        captured = capsys.readouterr()
        assert "WARNING" not in captured.out
        assert bs._transport_threads == []   # dead thread was removed

    def test_cancel_timers_clears_transport_threads(self):
        import threading
        bs, out = make_bankset({"default": {}})
        block = threading.Event()
        t = threading.Thread(target=block.wait, daemon=True)
        t.start()
        bs._transport_threads.append((t, time.monotonic(), "locate 0"))
        bs.cancel_timers()
        assert bs._transport_threads == []
        block.set()
        t.join(timeout=1)

    def test_real_transport_call_is_tracked_and_cleaned_up(
        self, fake_timer, mock_jack_ctrl
    ):
        """_run_jack_transport records the real thread it spawns, and
        _cleanup_timers drops it once the (fast, mocked) call completes."""
        import time as _time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
        }})
        bs.handle(make_pc(5))
        _time.sleep(0.05)     # let the real daemon thread finish
        bs._cleanup_timers()
        assert bs._transport_threads == []
        assert ("locate", 0) in mock_jack_ctrl.calls


# ---------------------------------------------------------------------------
# repeat_accel: accelerating repeat
# ---------------------------------------------------------------------------

class TestRepeatAccel:
    """Tests for repeat_accel: per-tier sequence and/or interval overrides."""

    # Standard three-tier config used by most tests.
    _CFG = {
        "default": {
            "CC3": {
                "repeat":          [{"send": "CC10", "value": 1}],
                "repeat_delay_ms": 400,
                "repeat_ms":       150,
                "repeat_accel": [
                    {"after_ms": 2000,
                     "repeat": [{"send": "CC10", "value": 2}]},
                    {"after_ms": 4000,
                     "repeat": [{"send": "CC10", "value": 5}],
                     "repeat_ms": 100},
                ],
            },
        },
    }

    def _press(self, bs, elapsed_s=0.0):
        """Press CC3 and backdate press_time to simulate elapsed hold."""
        bs.handle(make_cc(3, value=127))
        bs._gesture_press_time["CC3"] = time.time() - elapsed_s

    def test_base_seq_before_any_tier(self, fake_timer):
        """Before any tier threshold: base repeat sequence fires."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=0.5)   # 500ms < 2000ms
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].value == 1

    def test_tier1_seq_after_first_threshold(self, fake_timer):
        """After first tier's after_ms: tier 1 sequence fires."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=2.1)   # 2100ms >= 2000ms
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].value == 2

    def test_tier2_seq_after_second_threshold(self, fake_timer):
        """After second tier's after_ms: tier 2 sequence fires."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=4.1)   # 4100ms >= 4000ms
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].value == 5

    def test_tier_fires_exactly_at_threshold(self, fake_timer):
        """Tier activates when elapsed_ms equals after_ms exactly."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=2.0)   # exactly 2000ms
        fake_timer.active()[0].fire()
        assert out[0].value == 2

    def test_escalation_across_consecutive_fires(self, fake_timer):
        """Sequence escalates correctly across three consecutive fires."""
        bs, out = make_bankset(self._CFG)
        bs.handle(make_cc(3, value=127))

        bs._gesture_press_time["CC3"] = time.time() - 0.5
        fake_timer.active()[0].fire()   # base tier

        bs._gesture_press_time["CC3"] = time.time() - 2.1
        fake_timer.active()[0].fire()   # tier 1

        bs._gesture_press_time["CC3"] = time.time() - 4.1
        fake_timer.active()[0].fire()   # tier 2

        assert [e.value for e in out] == [1, 2, 5]

    def test_tier_repeat_ms_only_keeps_base_seq(self, fake_timer):
        """A tier with only repeat_ms inherits the base repeat sequence."""
        bs, out = make_bankset({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 200,
                "repeat_accel": [
                    {"after_ms": 1000, "repeat_ms": 50},
                ],
            },
        }})
        self._press(bs, elapsed_s=1.5)
        fake_timer.active()[0].fire()
        assert out[0].value == 1    # base sequence still fires

    def test_tier_repeat_ms_schedules_faster_next_timer(self, fake_timer):
        """A tier's repeat_ms is used for the next timer interval."""
        bs, out = make_bankset({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 200,
                "repeat_accel": [
                    {"after_ms": 1000, "repeat_ms": 50},
                ],
            },
        }})
        self._press(bs, elapsed_s=1.5)
        fake_timer.active()[0].fire()
        next_t = bs._gesture_repeat_timers.get("CC3")
        assert next_t is not None
        assert abs(next_t.delay - 0.05) < 0.001

    def test_no_tier_active_uses_base_repeat_ms(self, fake_timer):
        """Before any tier threshold the rescheduled timer uses base repeat_ms."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=0.5)
        fake_timer.active()[0].fire()
        next_t = bs._gesture_repeat_timers.get("CC3")
        assert next_t is not None
        assert abs(next_t.delay - 0.15) < 0.001   # 150ms base

    def test_tier2_repeat_ms_overrides_base(self, fake_timer):
        """Tier 2 (after 4s) carries its own repeat_ms=100ms."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=4.1)
        fake_timer.active()[0].fire()
        next_t = bs._gesture_repeat_timers.get("CC3")
        assert next_t is not None
        assert abs(next_t.delay - 0.10) < 0.001   # 100ms tier override

    def test_release_cancels_during_accel(self, fake_timer):
        """Release cancels pending repeat correctly while in an accel tier."""
        bs, out = make_bankset(self._CFG)
        self._press(bs, elapsed_s=2.1)
        fake_timer.active()[0].fire()            # one tier-1 repeat fires
        bs.handle(make_cc(3, value=0))           # release
        assert "CC3" not in bs._gesture_repeat_timers
        assert len(out) == 1

    def test_single_tap_unaffected_by_accel(self, fake_timer):
        """Quick release before first repeat fires: single action fires."""
        bs, out = make_bankset({"default": {
            "CC3": {
                "single":          [{"send": "CC20", "value": 127}],
                "repeat":          [{"send": "CC10", "value": 1}],
                "repeat_delay_ms": 500,
                "repeat_ms":       150,
                "repeat_accel": [
                    {"after_ms": 2000,
                     "repeat": [{"send": "CC10", "value": 5}]},
                ],
            },
        }})
        bs.handle(make_cc(3, value=127))
        result = bs.handle(make_cc(3, value=0))   # quick release
        assert result is not None
        assert len(result) == 1
        assert result[0].ctrl == 20

    def test_accel_tier_seq_supports_delay_key(self, fake_timer):
        """Sequences in accel tiers honour the 'delay' key normally."""
        bs, out = make_bankset({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 150,
                "repeat_accel": [
                    {"after_ms": 1000,
                     "repeat": [{"send": "CC10", "value": 5, "delay": 0.05}]},
                ],
            },
        }})
        self._press(bs, elapsed_s=1.5)
        t0 = fake_timer.active()[0]
        t0.fire()                           # fires tier seq (delayed item)

        # Immediate output is empty; a delay timer + the repeat reschedule
        # are now pending.
        assert len(out) == 0
        t_repeat = bs._gesture_repeat_timers.get("CC3")
        delay_t = next(
            t for t in fake_timer.active()
            if not getattr(t, "_fired", False) and t is not t_repeat
        )
        delay_t.fire()
        assert len(out) == 1
        assert out[0].value == 5

    def test_unsorted_tiers_still_work(self, fake_timer):
        """Tiers defined out of after_ms order are sorted automatically."""
        bs, out = make_bankset({"default": {
            "CC3": {
                "repeat":    [{"send": "CC10", "value": 1}],
                "repeat_ms": 150,
                "repeat_accel": [
                    {"after_ms": 4000, "repeat": [{"send": "CC10", "value": 5}]},
                    {"after_ms": 2000, "repeat": [{"send": "CC10", "value": 2}]},
                ],
            },
        }})
        self._press(bs, elapsed_s=2.5)   # between 2000 and 4000
        fake_timer.active()[0].fire()
        assert out[0].value == 2         # tier1, not tier2


# ---------------------------------------------------------------------------
# OSC send
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_osc_ctrl(monkeypatch):
    """Provide a mock osc_ctrl module so OSC tests run without python-osc.

    Patches sys.modules so that the lazy import inside _run_osc_send
    (``from midi_event_remapper import osc_ctrl``) gets the mock.
    """
    import sys, types
    calls = []
    mock = types.SimpleNamespace(
        send    = lambda host, port, address, args:
                      calls.append(("send", host, port, address, args)),
        preinit = lambda host, port: calls.append(("preinit", host, port)),
        calls   = calls,
    )
    monkeypatch.setitem(sys.modules, "midi_event_remapper.osc_ctrl", mock)
    # Also patch the package attribute: test_osc_ctrl.py imports osc_ctrl
    # at module level, which sets midi_event_remapper.osc_ctrl as a package
    # attribute.  Python's `from midi_event_remapper import osc_ctrl` then
    # returns that attribute directly, bypassing sys.modules entirely.
    import midi_event_remapper as _mer
    monkeypatch.setattr(_mer, "osc_ctrl", mock, raising=False)
    return mock


class TestOscSend:
    """Tests for the OSC send type."""

    def test_send_fires_non_blocking(self, fake_timer, mock_osc_ctrl):
        """OSC send must not block the mididings callback."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/test", "args": [1]}],
        }})
        t0 = time.time()
        bs.handle(make_pc(5))
        assert time.time() - t0 < 0.5

    def test_send_correct_arguments(self, fake_timer, mock_osc_ctrl):
        """send() must be called with the right host, port, address, args."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "10.0.0.1", "port": 7400,
                     "address": "/record/arm", "args": [1, 0.5, "ch1"]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert len(sends) == 1
        _, host, port, address, args = sends[0]
        assert host    == "10.0.0.1"
        assert port    == 7400
        assert address == "/record/arm"
        assert args    == [1, 0.5, "ch1"]

    def test_send_no_args_key(self, fake_timer, mock_osc_ctrl):
        """Omitting 'args' defaults to an empty list."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/ping"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert sends[0][4] == []   # args is empty list

    def test_send_empty_args_list(self, fake_timer, mock_osc_ctrl):
        """Explicit empty args list is forwarded as-is."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/ping", "args": []}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert sends[0][4] == []

    def test_send_integer_arg(self, fake_timer, mock_osc_ctrl):
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/v", "args": [42]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        assert mock_osc_ctrl.calls[-1][4] == [42]

    def test_send_float_arg(self, fake_timer, mock_osc_ctrl):
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/v", "args": [0.75]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        assert mock_osc_ctrl.calls[-1][4] == [0.75]

    def test_send_string_arg(self, fake_timer, mock_osc_ctrl):
        import time
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/v", "args": ["hello"]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        assert mock_osc_ctrl.calls[-1][4] == ["hello"]

    def test_send_multiple_targets(self, fake_timer, mock_osc_ctrl):
        """Two OSC sends in one sequence call send() twice."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [
                {"send": "OSC", "host": "127.0.0.1", "port": 9000,
                 "address": "/a"},
                {"send": "OSC", "host": "127.0.0.1", "port": 9001,
                 "address": "/b", "args": [1]},
            ],
        }})
        bs.handle(make_pc(5))
        time.sleep(0.05)
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert len(sends) == 2
        assert sends[0][3] == "/a" and sends[0][2] == 9000
        assert sends[1][3] == "/b" and sends[1][2] == 9001

    def test_send_no_midi_output(self, fake_timer, mock_osc_ctrl):
        """A pure OSC sequence produces no MIDI output."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/test"}],
        }})
        result = bs.handle(make_pc(5))
        assert result == []

    def test_send_combined_with_midi(self, fake_timer, mock_osc_ctrl):
        """OSC send alongside a MIDI send: MIDI output is returned."""
        import time
        bs, out = make_bankset({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "OSC", "host": "127.0.0.1", "port": 9000,
                 "address": "/trigger"},
            ],
        }})
        result = bs.handle(make_pc(5))
        time.sleep(0.05)
        assert len(result) == 1
        assert result[0].ctrl == 10
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert len(sends) == 1

    def test_send_delayed(self, fake_timer, mock_osc_ctrl):
        """Delayed OSC send schedules a timer."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/late", "delay": 0.5}],
        }})
        bs.handle(make_pc(5))
        assert len(fake_timer.active()) == 1

    def test_send_on_gesture(self, fake_timer, mock_osc_ctrl):
        """OSC send works inside a gesture sequence."""
        import time
        bs, out = make_bankset({"default": {
            "CC0": {
                "single": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                             "address": "/single"}],
                "double": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                             "address": "/double"}],
            },
        }})
        # Fire single: press, let multi-press window expire
        bs.handle(make_cc(0, value=127))
        fake_timer.active()[0].fire()
        time.sleep(0.05)
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert sends[-1][3] == "/single"

    def test_send_on_toggle(self, fake_timer, mock_osc_ctrl):
        """OSC send works in a toggle entry."""
        import time
        bs, out = make_bankset({"default": {
            "CC1": {
                "a": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                        "address": "/on",  "args": [1]}],
                "b": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                        "address": "/off", "args": [0]}],
            },
        }})
        bs.handle(make_cc(1, value=127))   # first press → "a" → /on
        time.sleep(0.05)
        sends = [c for c in mock_osc_ctrl.calls if c[0] == "send"]
        assert sends[-1][3] == "/on"
        assert sends[-1][4] == [1]


# ---------------------------------------------------------------------------
# eager_single
# ---------------------------------------------------------------------------

class TestEagerSingle:
    """
    Behavioral tests for the eager_single flag (§4 of EAGER_SINGLE_PLAN).

    Scenarios follow the plan's behavior walkthrough exactly:
    single fires at press time; long/double/repeat fire in addition,
    never re-firing single.
    """

    # ------------------------------------------------------------------
    # eager_single + double
    # ------------------------------------------------------------------

    def test_with_double_single_fires_on_press(self, fake_timer):
        """Press fires single immediately with no window delay."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})
        result = bs.handle(make_cc(5, value=127))
        # single fires immediately at press
        assert len(result) == 1
        assert result[0].ctrl == 10

    def test_with_double_lone_tap_fires_single_only(self, fake_timer):
        """Single tap → single fires at press; window fires nothing extra."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})
        result = bs.handle(make_cc(5, value=127))
        assert result[0].ctrl == 10        # eager single fired
        bs.handle(make_cc(5, value=0))     # release
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()      # window timer: count=1, single suppressed
        assert out == []                   # no second single via _fire_sequence

    def test_with_double_double_tap_fires_single_and_double(self, fake_timer):
        """Two presses → eager single on press1; double fires from window timer."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})
        # press 1 → eager single
        result1 = bs.handle(make_cc(5, value=127))
        assert result1[0].ctrl == 10
        bs.handle(make_cc(5, value=0))
        # press 2 resets the window timer
        result2 = bs.handle(make_cc(5, value=127))
        assert result2 == []               # count=2, no eager fire (only on count==1)
        bs.handle(make_cc(5, value=0))
        # fire window timer with count=2 → double
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 11           # double, not a second single

    # ------------------------------------------------------------------
    # eager_single + long
    # ------------------------------------------------------------------

    def test_with_long_short_press_fires_single_only(self, fake_timer):
        """Short press → eager single at press; quick release → single suppressed."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "long":   [{"send": "CC11", "value": 2}],
            },
        }}, long_press_ms=500)
        result = bs.handle(make_cc(5, value=127))
        assert result[0].ctrl == 10        # eager single
        release = bs.handle(make_cc(5, value=0))
        assert release == []               # single suppressed by eager guard
        assert out == []                   # no extra events via _output_fn

    def test_with_long_held_fires_single_and_long(self, fake_timer):
        """Hold past threshold → eager single at press, long from timer."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "long":   [{"send": "CC11", "value": 2}],
            },
        }}, long_press_ms=500)
        result = bs.handle(make_cc(5, value=127))
        assert result[0].ctrl == 10        # eager single on press
        # fire the long timer
        long_timers = [t for t in fake_timer.active() if t.delay >= 0.4]
        assert len(long_timers) == 1
        long_timers[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 11           # long fires; single not repeated

    # ------------------------------------------------------------------
    # eager_single + repeat
    # ------------------------------------------------------------------

    def test_with_repeat_quick_tap_fires_single_only(self, fake_timer):
        """Quick release before first repeat → single fires at press only."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "repeat": [{"send": "CC11", "value": 2}],
            },
        }})
        result = bs.handle(make_cc(5, value=127))
        assert result[0].ctrl == 10        # eager single on press
        release = bs.handle(make_cc(5, value=0))
        assert release == []               # single suppressed on quick-tap path
        assert out == []

    def test_with_repeat_held_fires_single_then_repeats(self, fake_timer):
        """Hold → single at press, then repeats; release does not re-fire single."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
                "repeat": [{"send": "CC11", "value": 2}],
            },
        }})
        result = bs.handle(make_cc(5, value=127))
        assert result[0].ctrl == 10        # eager single on press
        # fire the repeat delay timer → first repeat
        fake_timer.active()[0].fire()
        assert len(out) == 1
        assert out[0].ctrl == 11           # repeat (not a second single)
        # fire second repeat
        fake_timer.active()[0].fire()
        assert len(out) == 2
        # release after repeats fires nothing
        release = bs.handle(make_cc(5, value=0))
        assert release == []
        assert len(out) == 2

    # ------------------------------------------------------------------
    # only-single entry (fast path, flag redundant)
    # ------------------------------------------------------------------

    def test_only_single_fires_immediately(self):
        """eager_single on a single-only entry: fires immediately (same as without)."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "eager_single": True,
                "single": [{"send": "CC10", "value": 1}],
            },
        }})
        result = bs.handle(make_cc(5, value=127))
        # single-only fast path fires before eager block; behavior unchanged
        assert len(result) == 1
        assert result[0].ctrl == 10

    # ------------------------------------------------------------------
    # Entry without eager_single: no behavior change
    # ------------------------------------------------------------------

    def test_without_flag_single_deferred_to_release(self, fake_timer):
        """Without eager_single, single+double still defers single to window."""
        bs, out = make_bankset({"default": {
            "CC5": {
                "single": [{"send": "CC10", "value": 1}],
                "double": [{"send": "CC11", "value": 2}],
            },
        }})
        result = bs.handle(make_cc(5, value=127))
        assert result == []                # suppressed; no eager fire
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 10           # single fires from window timer


# ---------------------------------------------------------------------------
# Delayed-send threshold and leak detection
# ---------------------------------------------------------------------------

class TestDelayThreshold:
    """Verify _IMMEDIATE_DELAY_S behavior: zero and sub-threshold delays are
    sent synchronously; above-threshold delays go through the timer path."""

    def test_zero_delay_is_immediate(self):
        """delay: 0 sends synchronously — no timer spawned."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.0}],
        }})
        result = bs.handle(make_pc(5))
        assert len(result) == 1
        assert result[0].ctrl == 10

    def test_sub_threshold_delay_is_immediate(self, fake_timer):
        """delay <= 0.001 (1 ms) sends synchronously — no timer spawned."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.001}],
        }})
        result = bs.handle(make_pc(5))
        assert len(result) == 1
        assert result[0].ctrl == 10
        assert fake_timer.active() == []   # no timer was created

    def test_just_above_threshold_uses_timer(self, fake_timer):
        """delay: 0.002 (> 1 ms threshold) routes through the timer path."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.002}],
        }})
        result = bs.handle(make_pc(5))
        assert result == []
        assert len(fake_timer.active()) == 1
        fake_timer.active()[0].fire()
        assert out[0].ctrl == 10

    def test_zero_delay_does_not_populate_delay_send_threads(self):
        """Zero-delay sends must not add entries to _delay_send_threads."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.0}],
        }})
        bs.handle(make_pc(5))
        assert bs._delay_send_threads == []

    def test_real_delay_populates_delay_send_threads(self, fake_timer):
        """A real (above-threshold) delay adds a tracking entry."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.2}],
        }})
        bs.handle(make_pc(5))
        assert len(bs._delay_send_threads) == 1
        t, due_at, desc = bs._delay_send_threads[0]
        assert t.is_alive()
        assert "CC" in desc or "ctrl" in desc.lower()

    def test_delay_send_thread_removed_after_fire(self, fake_timer):
        """After a delayed timer fires, _delay_send_threads is cleaned up."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.2}],
        }})
        bs.handle(make_pc(5))
        assert len(bs._delay_send_threads) == 1
        fake_timer.active()[0].fire()
        # Trigger cleanup (simulate timer_list > 50 isn't feasible; call directly)
        bs._cleanup_timers()
        assert bs._delay_send_threads == []

    def test_cancel_timers_clears_delay_send_threads(self, fake_timer):
        """cancel_timers() clears _delay_send_threads."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.2}],
        }})
        bs.handle(make_pc(5))
        assert len(bs._delay_send_threads) == 1
        bs.cancel_timers()
        assert bs._delay_send_threads == []


class TestDelayLeakDetection:
    """Verify that _cleanup_timers warns once about stuck delay-send threads."""

    def test_overdue_thread_prints_warning(self, fake_timer, capsys):
        """A thread alive >1s past due gets a warning message."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.2}],
        }})
        bs.handle(make_pc(5))
        assert len(bs._delay_send_threads) == 1

        # Backdate due_at so it appears >1s overdue.
        t, due_at, desc = bs._delay_send_threads[0]
        bs._delay_send_threads[0] = (t, due_at - 2.0, desc)

        bs._cleanup_timers()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "stuck" in captured.out

    def test_overdue_thread_warned_only_once(self, fake_timer, capsys):
        """Second call to _cleanup_timers does not repeat the warning."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.2}],
        }})
        bs.handle(make_pc(5))
        t, due_at, desc = bs._delay_send_threads[0]
        bs._delay_send_threads[0] = (t, due_at - 2.0, desc)

        bs._cleanup_timers()
        capsys.readouterr()              # discard first warning
        bs._cleanup_timers()
        captured = capsys.readouterr()
        assert "WARNING" not in captured.out  # no second warning

    def test_completed_thread_not_warned(self, fake_timer, capsys):
        """A thread that completed on time produces no warning."""
        bs, out = make_bankset({"default": {
            "PC5": [{"send": "CC10", "value": 1, "delay": 0.2}],
        }})
        bs.handle(make_pc(5))
        fake_timer.active()[0].fire()    # thread completes
        bs._cleanup_timers()
        captured = capsys.readouterr()
        assert "WARNING" not in captured.out


# ---------------------------------------------------------------------------
# Send errors are reported even with debug off
# ---------------------------------------------------------------------------

class TestSendErrorsNotGatedOnDebug:
    """CMD / JACK_TRANSPORT / OSC failures used to be printed only when
    self._debug was set, so a failing send was silent in normal operation.
    They now go through urgent_print unconditionally.  Each runs in a
    spawned thread, hence the settle sleep."""

    SETTLE = 0.05

    def test_cmd_error_reported_without_debug(self, monkeypatch, capsys):
        import subprocess

        def _boom(*args, **kwargs):
            raise OSError("cmd exploded")

        monkeypatch.setattr(subprocess, "run", _boom)
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "CMD", "cmd": "true"}],
        }})
        bs._debug = False
        bs.handle(make_pc(5))
        time.sleep(self.SETTLE)

        captured = capsys.readouterr()
        assert "[cmd] ERROR" in captured.out
        assert "cmd exploded" in captured.out

    def test_jack_transport_error_reported_without_debug(
            self, monkeypatch, capsys):
        from midi_event_remapper import jack_ctrl

        def _boom(*args, **kwargs):
            raise RuntimeError("no jack")

        monkeypatch.setattr(jack_ctrl, "transport_locate", _boom)
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "JACK_TRANSPORT", "transport": "locate 0"}],
        }})
        bs._debug = False
        bs.handle(make_pc(5))
        time.sleep(self.SETTLE)

        captured = capsys.readouterr()
        assert "[jack_transport] ERROR" in captured.out
        assert "no jack" in captured.out

    def test_osc_error_reported_without_debug(self, monkeypatch, capsys):
        from midi_event_remapper import osc_ctrl

        def _boom(*args, **kwargs):
            raise RuntimeError("osc exploded")

        monkeypatch.setattr(osc_ctrl, "send", _boom)
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/test"}],
        }})
        bs._debug = False
        bs.handle(make_pc(5))
        time.sleep(self.SETTLE)

        captured = capsys.readouterr()
        assert "[osc] ERROR" in captured.out
        assert "osc exploded" in captured.out

    def test_send_errors_also_reach_stderr(self, monkeypatch, capsys):
        """urgent_print duplicates to stderr so the console sees faults
        even when stdout is redirected to the session log."""
        from midi_event_remapper import osc_ctrl

        def _boom(*args, **kwargs):
            raise RuntimeError("osc exploded")

        monkeypatch.setattr(osc_ctrl, "send", _boom)
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/test"}],
        }})
        bs._debug = False
        bs.handle(make_pc(5))
        time.sleep(self.SETTLE)

        captured = capsys.readouterr()
        assert "[osc] ERROR" in captured.err


# ---------------------------------------------------------------------------
# Timed return from a bank switch (snapback)
# ---------------------------------------------------------------------------

class _FakeClock:
    """Stands in for the ``time`` module inside bankset.py: monotonic() is
    controlled by the test, everything else (time.time for gestures)
    passes through to the real module."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


@pytest.fixture
def clock(monkeypatch):
    import midi_event_remapper.bankset as bankset_mod
    c = _FakeClock()
    monkeypatch.setattr(bankset_mod, "time", c)
    return c


# PC5 sends a different CC in each bank, which shows where a press landed.
SNAPBACK_BANKS = {
    "looper": {
        "PC1": [{"send": "BANK", "bank": "drums", "snapback_after_ms": 4000}],
        "PC2": [{"send": "BANK", "bank": "drums"}],
        "PC5": [{"send": "CC13", "value": 127}],
    },
    "drums": {
        "PC1": [{"send": "BANK", "bank": "tap", "snapback_after_ms": 6000}],
        "PC3": [{"send": "BANK", "bank": "tap"}],
        "PC4": [{"send": "BANK", "bank": "looper"}],
        "PC5": [{"send": "CC0", "value": 127}],
        "CC1": {"single":  [{"send": "CC20", "value": 127}],
                "long":    [{"send": "CC21", "value": 127}],
                "long_ms": 500},
        ("CC2", "CC3"): {"single": [{"send": "CC22", "value": 127}]},
        "CC4": [{"send": "CC40"}],                       # direct
        "CC5": {"a": [{"send": "CC50", "value": 127}],   # toggle
                "b": [{"send": "CC50", "value": 0}]},
        "PC6": [{"send": "SNAPBACK_CANCEL"}],
        "CC6": {"single":          [{"send": "CC60", "value": 127}],   # tempo up
                "repeat":          [{"send": "CC60", "value": 127}],
                "repeat_delay_ms": 400,
                "repeat_ms":       100},
        "CC7": [{"send": "CC70", "press_only": True}],   # direct, no release
        "CC8": {"single": [{"send": "CC80", "value": 127}],
                "double": [{"send": "CC81", "value": 127}]},
        "CC10": {"single": [{"send": "CC90", "value": 127}]},
    },
    "tap": {
        "PC2": [{"send": "BANK", "bank": "drums"}],
        "PC5": [{"send": "CC1", "value": 127}],
    },
}


def _landed(result):
    """CC number the PC5 press produced: 13 looper, 0 drums, 1 tap."""
    assert len(result) == 1
    return result[0].ctrl


class TestSnapback:

    @pytest.fixture(autouse=True)
    def _timers(self, fake_timer):
        self.timers = fake_timer

    def _bs(self, active_bank="looper"):
        bs, captured = make_bankset(SNAPBACK_BANKS, active_bank=active_bank)
        return bs, captured

    @staticmethod
    def _fire(bs):
        """Fire the current snapback timer (as if it had woken up)."""
        bs._snapback_timer.fire()

    # -- filling the slot ------------------------------------------------

    def test_timed_switch_fills_slot_and_starts_timer(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        assert bs.active_bank == "drums"
        assert bs._snapback_bank == "looper"
        assert bs._snapback_deadline == 1004.0
        assert bs._snapback_timer.delay == 4.0

    def test_plain_switch_leaves_slot_empty(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(2))
        assert bs.active_bank == "drums"
        assert bs._snapback_bank is None
        assert bs._snapback_timer is None

    def test_rig_long_press_switch_fills_slot(self, clock):
        """The rig's shape: looper CC0 long sends CC64 then a timed BANK,
        fired from the long-press timer thread."""
        bs, captured = make_bankset({
            "looper": {
                "CC0": {
                    "single":  [{"send": "CC2", "value": 127}],
                    "long":    [{"send": "CC64", "value": 127},
                                {"send": "BANK", "bank": "drums-lst",
                                 "snapback_after_ms": 4000}],
                    "long_ms": 500,
                },
            },
            "drums-lst": {},
        }, active_bank="looper")
        bs.handle(make_cc(0, value=127))
        self.timers.active()[0].fire()          # long threshold reached
        assert [e.ctrl for e in captured] == [64]
        assert bs.active_bank == "drums-lst"
        assert bs._snapback_bank == "looper"
        # The suppressed release after the long press is not a new press.
        assert bs.handle(make_cc(0, value=0)) == []
        assert not bs._held_keys
        clock.now = 1004.1
        self._fire(bs)
        assert bs.active_bank == "looper"

    # -- the timer -------------------------------------------------------

    def test_snaps_back_automatically_when_idle(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1004.0
        self._fire(bs)
        assert bs.active_bank == "looper"
        assert bs._snapback_bank is None
        assert _landed(bs.handle(make_pc(5))) == 13

    def test_snapback_updates_display(self, clock):
        bs, _ = self._bs()
        shown = []
        bs._display_fn = lambda bset, bank, style: shown.append(bank)
        bs.handle(make_pc(1))
        clock.now = 1004.0
        self._fire(bs)
        assert shown == ["drums", "looper"]

    def test_pedal_use_moves_deadline_timer_sleeps_again(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1003.0
        assert _landed(bs.handle(make_pc(5))) == 0
        assert bs._snapback_deadline == 1007.0
        clock.now = 1004.0
        self._fire(bs)                          # wakes at the old deadline
        assert bs.active_bank == "drums"
        assert bs._snapback_timer.delay == pytest.approx(3.0)
        clock.now = 1007.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_mapped_release_moves_deadline(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        bs.handle(make_cc(4, value=127))
        clock.now = 1003.0
        bs.handle(make_cc(4, value=0))
        assert bs._snapback_deadline == 1007.0

    def test_unmapped_events_do_not_move_deadline(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1003.0
        assert bs.handle(make_cc(9, value=127)) is None   # passed through
        bs.handle(make_cc(9, value=0))
        assert bs._snapback_deadline == 1004.0
        assert not bs._held_keys
        clock.now = 1004.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    # -- held pedals -----------------------------------------------------

    def _held_blocks(self, clock, press, release):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        for ev in press:
            bs.handle(ev)
        clock.now = 1010.0
        self._fire(bs)                          # deadline passed, but held
        assert bs.active_bank == "drums"
        assert bs._snapback_timer.delay == 0.25
        for ev in release:
            bs.handle(ev)                       # released at 1010
        assert not bs._held_keys
        self._fire(bs)                          # poll: deadline moved
        assert bs.active_bank == "drums"
        clock.now = 1014.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_held_gesture_pedal_blocks_snapback(self, clock):
        self._held_blocks(clock, [make_cc(1, value=127)],
                          [make_cc(1, value=0)])

    def test_held_direct_pedal_blocks_snapback(self, clock):
        """A direct entry that forwards its release keeps the bank until
        the release, so the release reaches the same mapping."""
        self._held_blocks(clock, [make_cc(4, value=127)],
                          [make_cc(4, value=0)])

    def _not_held(self, clock, press):
        """Presses whose mapping does not need the release are a moment
        of use only: a pedal left down (or latched) does not hold the
        bank."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1001.0
        for ev in press:
            bs.handle(ev)
        assert not bs._held_keys
        assert bs._snapback_deadline == 1005.0  # still counted as use
        clock.now = 1005.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_chord_press_does_not_hold(self, clock):
        self._not_held(clock, [make_cc(2, value=127), make_cc(3, value=127)])

    def test_toggle_press_does_not_hold(self, clock):
        self._not_held(clock, [make_cc(5, value=127)])

    def test_press_only_direct_does_not_hold(self, clock):
        self._not_held(clock, [make_cc(7, value=127)])

    def test_multipress_gesture_does_not_hold(self, clock):
        self._not_held(clock, [make_cc(8, value=127)])

    def test_latching_pedal_on_toggle(self, clock):
        """A latching pedal sends 127 on one press and 0 on the next; on a
        toggle each one is just use, and the bank still snaps back."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1001.0
        bs.handle(make_cc(5, value=127))        # latched on
        clock.now = 1002.0
        bs.handle(make_cc(5, value=0))          # latched off
        assert bs._snapback_deadline == 1006.0
        clock.now = 1006.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    # -- non-momentary pedals -------------------------------------------
    # Trigger-only: sends 127 on every press, never 0.
    # Latching: sends 127 on one press and 0 on the next.

    def _non_momentary(self, clock, values, ctrl):
        """Send ``values`` on CC ``ctrl`` one second apart starting at
        1001; the key never holds, every event counts as use, and the bank
        snaps back the timeout after the last one."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        t = 1001.0
        for v in values:
            clock.now = t
            bs.handle(make_cc(ctrl, value=v))
            for timer in self.timers.active():  # let gesture windows close
                if timer is not bs._snapback_timer:
                    timer.fire()
            assert not bs._held_keys
            t += 1.0
        last = t - 1.0
        assert bs._snapback_deadline == last + 4.0
        clock.now = last + 4.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    @pytest.mark.parametrize("ctrl", [5, 7, 8, 10],
                             ids=["toggle", "press_only_direct",
                                  "multipress_gesture", "single_gesture"])
    def test_trigger_only_pedal(self, clock, ctrl):
        self._non_momentary(clock, [127, 127, 127], ctrl)

    @pytest.mark.parametrize("ctrl", [5, 7, 8, 10],
                             ids=["toggle", "press_only_direct",
                                  "multipress_gesture", "single_gesture"])
    def test_latching_pedal(self, clock, ctrl):
        self._non_momentary(clock, [127, 0, 127, 0], ctrl)

    def test_trigger_only_chord(self, clock):
        """Chord members pressed again without releases never hold."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        for t in (1001.0, 1002.0):
            clock.now = t
            bs.handle(make_cc(2, value=127))
            bs.handle(make_cc(3, value=127))
        assert not bs._held_keys
        clock.now = 1006.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_latching_pedal_on_release_forwarding_direct_holds(self, clock):
        """On a direct entry that forwards releases, a latched-on pedal
        holds the bank until it sends 0 (its 0 must reach this mapping)."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        bs.handle(make_cc(4, value=127))        # latched on
        clock.now = 1100.0
        self._fire(bs)
        assert bs.active_bank == "drums"
        bs.handle(make_cc(4, value=0))          # latched off at 1100
        clock.now = 1103.9
        self._fire(bs)                          # poll: deadline now 1104
        assert bs.active_bank == "drums"
        clock.now = 1104.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_hold_keys_follow_mapping_needs(self, clock):
        bs, _ = self._bs()
        assert bs._hold_keys["drums"] == {"CC1", "CC4", "CC6"}
        assert bs._hold_keys["looper"] == set()   # PC keys never hold

    def test_holding_a_repeat_pedal_counts_as_activity(self, clock):
        """Holding the tempo-repeat pedal keeps the drum bank however long
        it is held; the idle time starts at the release."""
        bs, captured = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1001.0
        bs.handle(make_cc(6, value=127))        # hold: repeats start
        repeat = bs._gesture_repeat_timers["CC6"]
        for _ in range(5):
            repeat.fire()
            repeat = bs._gesture_repeat_timers["CC6"]
        assert [e.ctrl for e in captured] == [60] * 5
        clock.now = 1020.0                      # held for 19 s
        self._fire(bs)
        assert bs.active_bank == "drums"
        bs.handle(make_cc(6, value=0))          # release at 1020
        clock.now = 1023.9
        self._fire(bs)
        assert bs.active_bank == "drums"
        clock.now = 1024.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_missed_release_cleared_by_next_press(self, clock):
        """A key pressed in another bank whose release was lost is cleared
        by its next press, even where the key is unmapped."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        bs.handle(make_cc(4, value=127))        # its release is lost
        bs.handle(make_pc(3))                   # drums -> tap; CC4 unmapped
        assert bs._held_keys == {"CC4"}
        bs.handle(make_cc(4, value=127))
        assert not bs._held_keys

    def test_release_in_other_bank_clears_held(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        bs.handle(make_cc(4, value=127))
        bs.handle(make_pc(3))                   # drums -> tap; CC4 unmapped
        bs.handle(make_cc(4, value=0))
        assert not bs._held_keys

    # -- slot rules ------------------------------------------------------

    def test_plain_switch_cancels_snapback(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))                   # looper -> drums, timed
        bs.handle(make_pc(3))                   # drums -> tap, plain
        assert bs.active_bank == "tap"
        assert bs._snapback_bank is None
        clock.now = 1100.0
        self._fire(bs)
        assert bs.active_bank == "tap"

    def test_plain_switch_away_and_back_stays_canceled(self, clock):
        """The rig case: looper -> drums-lst (timed) -> drums-tap -> back
        to drums-lst by hand.  No snapback."""
        bs, _ = self._bs()
        bs.handle(make_pc(1))                   # looper -> drums, timed
        bs.handle(make_pc(3))                   # drums -> tap, plain
        bs.handle(make_pc(2))                   # tap -> drums, plain
        assert bs.active_bank == "drums"
        assert bs._snapback_bank is None
        clock.now = 1100.0
        self._fire(bs)
        assert bs.active_bank == "drums"

    def test_arriving_at_target_by_hand_empties_slot(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        timer = bs._snapback_timer
        bs.handle(make_pc(4))                   # drums -> looper by hand
        assert bs._snapback_bank is None
        bs.handle(make_pc(2))                   # looper -> drums, plain
        clock.now = 1010.0
        timer.fire()                            # stale timer does nothing
        assert bs.active_bank == "drums"

    def test_second_timed_switch_keeps_target_new_timeout(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))                   # looper -> drums, 4 s
        first = bs._snapback_timer
        clock.now = 1001.0
        bs.handle(make_pc(1))                   # drums -> tap, 6 s
        assert bs.active_bank == "tap"
        assert bs._snapback_bank == "looper"
        assert bs._snapback_deadline == 1007.0
        assert bs._snapback_timer is not first
        assert bs._snapback_timer.delay == 6.0
        clock.now = 1005.0
        first.fire()                            # old chain exits
        assert bs.active_bank == "tap"
        clock.now = 1007.0
        self._fire(bs)
        assert bs.active_bank == "looper"

    def test_cancel_timers_empties_slot_and_stops_timer(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        timer = bs._snapback_timer
        bs.cancel_timers()
        assert bs._snapback_bank is None
        assert timer.canceled

    # -- SNAPBACK_CANCEL -------------------------------------------------

    def test_cancel_keeps_current_bank(self, clock):
        bs, _ = self._bs()
        bs.handle(make_pc(1))
        clock.now = 1003.0
        assert bs.handle(make_pc(6)) == []
        assert bs._snapback_bank is None
        clock.now = 1100.0
        self._fire(bs)
        assert bs.active_bank == "drums"

    def test_cancel_with_empty_slot_is_harmless(self, clock):
        bs, _ = self._bs(active_bank="drums")
        assert bs.handle(make_pc(6)) == []
        assert bs.active_bank == "drums"
