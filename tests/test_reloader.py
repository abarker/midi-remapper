"""test_reloader.py

Tests for the live config file reloader.
"""
import time
import threading
import tempfile
import types
from pathlib import Path

import pytest
from conftest import make_bankset, make_cc

from midi_event_remapper.reloader import ConfigReloader
from midi_event_remapper.bankset import BankSet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_config(path, content):
    """Overwrite path with content, ensuring a new mtime."""
    path.write_text(content)


def make_global_config(banksets):
    """Return a minimal module-like object with a BANK_SETS list."""
    cfg = types.SimpleNamespace()
    cfg.BANK_SETS = list(banksets)
    return cfg


def simple_config_text(name="test", bank_name="default", cc_send="CC4"):
    """Return config file text for a single-bank BankSet."""
    return (
        f'{{\n'
        f'    "name": "{name}",\n'
        f'    "banks": {{\n'
        f'        "{bank_name}": {{\n'
        f'            "CC0": [{{"send": "{cc_send}", "press_only": True}}],\n'
        f'        }},\n'
        f'    }},\n'
        f'}}\n'
    )


def make_temp_config(content):
    """Write content to a named temp .py file; return its Path."""
    f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


def make_reloader(paths, banksets, display=None, **kwargs):
    """Build a ConfigReloader with a SimpleNamespace global_config."""
    cfg = make_global_config(banksets)
    rl  = ConfigReloader(paths, cfg, display=display, **kwargs)
    return rl, cfg


# ---------------------------------------------------------------------------
# cancel_timers
# ---------------------------------------------------------------------------

class TestCancelTimers:

    def test_cancel_gesture_timers(self, fake_timer):
        bs, _ = make_bankset({
            "default": {
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "double": [{"send": "CC20", "value": 127}],
                },
            }
        })
        bs.handle(make_cc(1, value=127))
        assert len(fake_timer.active()) > 0
        bs.cancel_timers()
        assert all(t.cancelled for t in fake_timer.instances)

    def test_cancel_long_timer(self, fake_timer):
        bs, _ = make_bankset({
            "default": {
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "long":   [{"send": "CC20", "value": 127}],
                },
            }
        })
        bs.handle(make_cc(1, value=127))
        assert len(fake_timer.active()) > 0
        bs.cancel_timers()
        assert all(t.cancelled for t in fake_timer.instances)

    def test_cancel_clears_timer_list(self, fake_timer):
        bs, _ = make_bankset({
            "default": {
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "double": [{"send": "CC20", "value": 127}],
                },
            }
        })
        bs.handle(make_cc(1, value=127))
        bs.cancel_timers()
        assert bs._timer_list == []

    def test_cancel_idempotent_on_empty(self):
        bs, _ = make_bankset({"default": {}})
        bs.cancel_timers()   # Should not raise.
        bs.cancel_timers()


# ---------------------------------------------------------------------------
# ConfigReloader internals (no real thread needed)
# ---------------------------------------------------------------------------

class TestReloaderMtimes:

    def test_detects_new_mtime(self):
        path = make_temp_config(simple_config_text())
        bs, cfg = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs])

        # Overwrite with a tiny delay to guarantee a new mtime.
        time.sleep(0.05)
        write_config(path, simple_config_text(cc_send="CC10"))
        new = rl._current_mtimes()
        assert new[path] != rl._last_mtimes[path]
        path.unlink()

    def test_missing_file_returns_none_mtime(self):
        path = Path("/tmp/does_not_exist_xyz.py")
        bs, cfg = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs])
        assert rl._current_mtimes()[path] is None


# ---------------------------------------------------------------------------
# Full reload cycle (using _reload directly, no background thread)
# ---------------------------------------------------------------------------

class TestReloadCycle:

    def test_successful_reload_swaps_banksets(self):
        path = make_temp_config(simple_config_text(cc_send="CC4"))
        bs, _ = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs])

        write_config(path, simple_config_text(cc_send="CC99"))
        rl._reload([path])

        assert gcfg.BANK_SETS[0].banks["default"]["CC0"][0]["send"] == "CC99"
        path.unlink()

    def test_active_bank_preserved_after_reload(self):
        content_a = (
            '{\n'
            '    "name": "test",\n'
            '    "banks": {\n'
            '        "default": {"CC0": [{"send": "CC4", "press_only": True}]},\n'
            '        "drums":   {"CC0": [{"send": "CC8", "press_only": True}]},\n'
            '    },\n'
            '}\n'
        )
        path = make_temp_config(content_a)
        from midi_event_remapper.loader import load_bankset_file
        (old_bs,) = load_bankset_file(path)
        old_bs.active_bank = "drums"

        rl, gcfg = make_reloader([path], [old_bs])
        gcfg.BANK_SETS = [old_bs]

        write_config(path, content_a)   # Same banks; just trigger a reload.
        rl._reload([path])

        assert gcfg.BANK_SETS[0].active_bank == "drums"
        path.unlink()

    def test_active_bank_reset_when_bank_removed(self):
        content_two = (
            '{\n'
            '    "name": "test",\n'
            '    "banks": {\n'
            '        "default": {"CC0": [{"send": "CC4", "press_only": True}]},\n'
            '        "drums":   {"CC0": [{"send": "CC8", "press_only": True}]},\n'
            '    },\n'
            '}\n'
        )
        content_one = (
            '{\n'
            '    "name": "test",\n'
            '    "banks": {\n'
            '        "default": {"CC0": [{"send": "CC4", "press_only": True}]},\n'
            '    },\n'
            '}\n'
        )
        path = make_temp_config(content_two)
        from midi_event_remapper.loader import load_bankset_file
        (old_bs,) = load_bankset_file(path)
        old_bs.active_bank = "drums"

        rl, gcfg = make_reloader([path], [old_bs])
        gcfg.BANK_SETS = [old_bs]

        # Overwrite with a config that no longer has "drums".
        write_config(path, content_one)
        rl._reload([path])

        # Should fall back to the new config's default, not error.
        assert gcfg.BANK_SETS[0].active_bank == "default"
        path.unlink()

    def test_output_fn_transferred(self):
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        sentinel = object()
        bs._output_fn = sentinel

        rl, gcfg = make_reloader([path], [bs])
        gcfg.BANK_SETS = [bs]
        rl._reload([path])

        assert gcfg.BANK_SETS[0]._output_fn is sentinel
        path.unlink()

    def test_display_fn_transferred(self):
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        sentinel = lambda *args: None
        bs._display_fn = sentinel

        rl, gcfg = make_reloader([path], [bs])
        gcfg.BANK_SETS = [bs]
        rl._reload([path])

        # The function object is transferred to the new BankSet.
        assert gcfg.BANK_SETS[0]._display_fn is sentinel
        path.unlink()

    def test_parse_error_keeps_old_config(self):
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs])
        gcfg.BANK_SETS = [bs]

        write_config(path, "this is not valid {{{")
        rl._reload([path])

        # BANK_SETS must be unchanged.
        assert gcfg.BANK_SETS[0] is bs
        path.unlink()

    def test_validation_error_keeps_old_config(self):
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs])
        gcfg.BANK_SETS = [bs]

        # Missing 'send' key is a validation error.
        bad = (
            '{"name": "test", "banks": {"default": {"CC0": [{"value": 127}]}}}\n'
        )
        write_config(path, bad)
        rl._reload([path])

        assert gcfg.BANK_SETS[0] is bs
        path.unlink()

    def test_old_timers_cancelled_on_reload(self, fake_timer):
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({
            "default": {
                "CC1": {
                    "single": [{"send": "CC10", "value": 127}],
                    "double": [{"send": "CC20", "value": 127}],
                },
            }
        })
        # Create a pending timer by pressing CC1.
        bs.handle(make_cc(1, value=127))
        assert len(fake_timer.active()) > 0

        rl, gcfg = make_reloader([path], [bs])
        gcfg.BANK_SETS = [bs]
        rl._reload([path])

        # All original timers should now be cancelled.
        assert all(t.cancelled for t in fake_timer.instances)
        path.unlink()


# ---------------------------------------------------------------------------
# Background thread integration (brief real-time test)
# ---------------------------------------------------------------------------

class TestReloaderThread:

    def test_detects_file_change(self):
        path = make_temp_config(simple_config_text(cc_send="CC4"))
        from midi_event_remapper.loader import load_bankset_file
        (bs,) = load_bankset_file(path)

        rl, gcfg = make_reloader([path], [bs], interval_s=0.05)
        gcfg.BANK_SETS = [bs]
        rl.start()

        try:
            time.sleep(0.1)   # Let first poll pass without triggering.
            write_config(path, simple_config_text(cc_send="CC77"))
            time.sleep(0.3)   # Wait for poll + reload.
            assert gcfg.BANK_SETS[0].banks["default"]["CC0"][0]["send"] == "CC77"
        finally:
            rl.stop()
            path.unlink()

    def test_stop_is_clean(self):
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs], interval_s=0.05)
        rl.start()
        rl.stop()
        assert not rl._thread.is_alive()
        path.unlink()


class TestDisplayStyles:

    def test_display_stripped_from_bank(self):
        """_display is removed from the bank mapping dict by the loader."""
        content = '\n'.join([
            '{',
            '    "name": "test",',
            '    "banks": {',
            '        "default": {',
            '            "_display": {"bg": "#1a2e1a", "fg": "#a0ffb0"},',
            '            "CC0": [{"send": "CC4", "press_only": True}],',
            '        },',
            '    },',
            '}',
        ])
        path = make_temp_config(content)
        from midi_event_remapper.loader import load_bankset_file
        (bs,) = load_bankset_file(path)
        assert "_display" not in bs.banks["default"]
        assert bs._display_styles["default"]["bg"] == "#1a2e1a"
        path.unlink()

    def test_display_style_passed_on_switch(self):
        """switch_bank passes the correct style dict to _display_fn."""
        content = '\n'.join([
            '{',
            '    "name": "test",',
            '    "banks": {',
            '        "default": {},',
            '        "drums": {',
            '            "_display": {"bg": "#1a2e1a", "fg": "#a0ffb0"},',
            '        },',
            '    },',
            '}',
        ])
        path = make_temp_config(content)
        from midi_event_remapper.loader import load_bankset_file
        (bs,) = load_bankset_file(path)
        calls = []
        bs._display_fn = lambda *args: calls.append(args)
        bs.switch_bank("drums")
        assert len(calls) == 1
        assert calls[0][2] == {"bg": "#1a2e1a", "fg": "#a0ffb0"}
        path.unlink()

    def test_no_display_key_gives_none_style(self):
        """A bank without _display passes None as the style to _display_fn."""
        content = '\n'.join([
            '{',
            '    "name": "test",',
            '    "banks": {',
            '        "default": {},',
            '        "other": {},',
            '    },',
            '}',
        ])
        path = make_temp_config(content)
        from midi_event_remapper.loader import load_bankset_file
        (bs,) = load_bankset_file(path)
        calls = []
        bs._display_fn = lambda *args: calls.append(args)
        bs.switch_bank("other")
        assert calls[0][2] is None
        path.unlink()

    def test_reload_applies_new_styles_immediately(self):
        """After a reload the display is updated with the new style at once.

        The update goes through _refresh_display which calls display.update()
        directly, not through bs._display_fn.
        """
        content_before = '\n'.join([
            '{',
            '    "name": "test",',
            '    "banks": {"default": {}},',
            '}',
        ])
        content_after = '\n'.join([
            '{',
            '    "name": "test",',
            '    "banks": {',
            '        "default": {',
            '            "_display": {"bg": "#ff0000"},',
            '        },',
            '    },',
            '}',
        ])
        path = make_temp_config(content_before)
        from midi_event_remapper.loader import load_bankset_file
        (bs,) = load_bankset_file(path)

        # Build a minimal display stub with current_bankset_name tracking.
        import types
        display = types.SimpleNamespace(
            current_bankset_name = "test",
            calls = [],
        )
        display.update = lambda *args: display.calls.append(args)

        rl, gcfg = make_reloader([path], [bs], interval_s=0.05, display=display)
        gcfg.BANK_SETS = [bs]
        write_config(path, content_after)
        rl._reload([path])

        assert len(display.calls) == 1
        assert display.calls[-1][2] == {"bg": "#ff0000"}
        path.unlink()


class TestTransferStateNameMatch:

    def test_active_bank_not_copied_from_fallback_bankset(self):
        """Active bank must only be preserved when BankSet names match.

        If a new BankSet has no name match in the old config, the fallback
        old BankSet must not donate its active bank to the new one.
        """
        # Old config: one bankset "alpha" on bank "special".
        content_old = '\n'.join([
            '{',
            '    "name": "alpha",',
            '    "banks": {',
            '        "default": {},',
            '        "special": {},',
            '    },',
            '}',
        ])
        # New config: completely different bankset name "beta".
        content_new = '\n'.join([
            '{',
            '    "name": "beta",',
            '    "active_bank": "default",',
            '    "banks": {',
            '        "default": {},',
            '        "other": {},',
            '    },',
            '}',
        ])
        path_old = make_temp_config(content_old)
        path_new = make_temp_config(content_new)

        from midi_event_remapper.loader import load_bankset_file
        (old_bs,) = load_bankset_file(path_old)
        old_bs.active_bank = "special"

        rl, gcfg = make_reloader([path_new], [old_bs], interval_s=0.05)
        gcfg.BANK_SETS = [old_bs]
        rl._reload([path_new])

        # "beta" must start on its own configured active_bank, not "special".
        assert gcfg.BANK_SETS[0].active_bank == "default"
        path_old.unlink()
        path_new.unlink()


class TestRefreshDisplay:
    """Tests for the single targeted display update after reload."""

    def _make_display_stub(self, current_name=None):
        import types
        d = types.SimpleNamespace(
            current_bankset_name = current_name,
            calls                = [],
        )
        d.update = lambda *args: d.calls.append(args)
        return d

    def test_shows_currently_displayed_bankset(self):
        """Reload pushes update for the bankset currently shown, not the last one."""
        # Two banksets: "global" (1 bank) then "actition" (2 banks) --
        # same order as the real actition.py config.
        global_content = '\n'.join([
            '{',
            '    "name": "global",',
            '    "banks": {"default": {}},',
            '}',
        ])
        actition_content = '\n'.join([
            '{',
            '    "name": "actition",',
            '    "banks": {"default": {}, "drums": {}},',
            '    "active_bank": "drums",',
            '}',
        ])
        # Pack both into one file as a list, actition first (like the real config).
        combined = '\n'.join([
            '[',
            '{',
            '    "name": "actition",',
            '    "banks": {"default": {}, "drums": {}},',
            '    "active_bank": "drums",',
            '},',
            '{',
            '    "name": "global",',
            '    "banks": {"default": {}},',
            '},',
            ']',
        ])
        path = make_temp_config(combined)
        from midi_event_remapper.loader import load_bankset_file
        banksets = load_bankset_file(path)   # [actition_bs, global_bs]

        # Display is currently showing "actition".
        display = self._make_display_stub(current_name="actition")

        rl, gcfg = make_reloader([path], banksets,
                                  display=display, interval_s=0.05)
        gcfg.BANK_SETS = list(banksets)
        rl._reload([path])

        # Exactly one update, and it must be for "actition", not "global".
        assert len(display.calls) == 1
        assert display.calls[0][0] == "actition"
        path.unlink()

    def test_falls_back_to_multi_bank_when_no_current_match(self):
        """Falls back to the first multi-bank bankset when display has no match."""
        combined = '\n'.join([
            '[',
            '{',
            '    "name": "single",',
            '    "banks": {"default": {}},',
            '},',
            '{',
            '    "name": "multi",',
            '    "banks": {"default": {}, "layer2": {}},',
            '},',
            ']',
        ])
        path = make_temp_config(combined)
        from midi_event_remapper.loader import load_bankset_file
        banksets = load_bankset_file(path)

        # Display was showing something that no longer exists.
        display = self._make_display_stub(current_name="gone")

        rl, gcfg = make_reloader([path], banksets,
                                  display=display, interval_s=0.05)
        gcfg.BANK_SETS = list(banksets)
        rl._reload([path])

        assert len(display.calls) == 1
        assert display.calls[0][0] == "multi"
        path.unlink()

    def test_no_update_when_display_is_none(self):
        """No display push when no display is attached to the reloader."""
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs], display=None, interval_s=0.05)
        gcfg.BANK_SETS = [bs]
        # Should complete without error and without touching any display.
        rl._reload([path])
        path.unlink()


class TestWatcherRobustness:

    def test_watcher_survives_reload_exception(self):
        """An unexpected exception in _reload must not kill the watcher thread."""
        path = make_temp_config(simple_config_text())
        bs, _ = make_bankset({"default": {}})
        rl, gcfg = make_reloader([path], [bs], interval_s=0.05)
        gcfg.BANK_SETS = [bs]
        rl.start()

        try:
            # Patch _reload to raise on the first call, then succeed.
            calls = []
            original_reload = rl._reload

            def flaky(changed):
                calls.append(len(calls))
                if len(calls) == 1:
                    raise RuntimeError("simulated unexpected error")
                original_reload(changed)

            rl._reload = flaky

            # Touch the file to trigger a reload.
            import time
            time.sleep(0.1)
            write_config(path, simple_config_text(cc_send="CC50"))
            time.sleep(0.4)

            # Thread must still be alive after the exception.
            assert rl._thread.is_alive()
        finally:
            rl.stop()
            path.unlink()

    def test_cancelled_bankset_does_not_emit_on_delayed_send(self, fake_timer):
        """A delayed-send timer that fires after cancel_timers must not emit."""
        bs, captured = make_bankset({
            "default": {
                "CC1": [{"send": "CC10", "value": 127, "delay": 0.5}],
            }
        })
        bs.handle(make_cc(1, value=127))
        # One delayed-send timer should be pending.
        assert len(fake_timer.active()) == 1
        delayed_timer = fake_timer.instances[-1]

        bs.cancel_timers()
        assert bs._active is False

        delayed_timer.fire()   # Simulates the race.

        assert captured == []

    def test_fire_sequence_suppressed_after_cancel(self, fake_timer):
        """_fire_sequence must not call _output_fn after cancel_timers."""
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

        # Simulate: timer fires just as cancel is called.
        bs._active = False   # cancel_timers sets this first
        window_timer.fire()  # gesture multipress fire -> calls _fire_sequence

        assert captured == []
