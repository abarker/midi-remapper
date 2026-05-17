"""
test_bankset.py

Tests for BankSet event-handling behaviour: direct mappings, toggles,
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
        # Quick release: long timer cancelled, single fires via return value.
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
        assert not bs._gesture_repeat_timers["CC0"].cancelled

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
        # The rescheduled repeat timer should be cancelled.
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

    def test_chord_timer_cancelled_on_completion(self, fake_timer):
        bs, out = self._make()
        bs.handle(make_pc(4))
        bs.handle(make_pc(5))
        assert all(t.cancelled for t in fake_timer.instances)

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
        # should be cancelled without dispatching any fallback.
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
        # ("CC2","CC3") window should be cancelled, no fallback
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
