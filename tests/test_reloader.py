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


def make_reloader(paths, banksets, **kwargs):
    """Build a ConfigReloader with a SimpleNamespace global_config."""
    cfg = make_global_config(banksets)
    rl  = ConfigReloader(paths, cfg, **kwargs)
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
        called = []
        bs._display_fn = called.append

        rl, gcfg = make_reloader([path], [bs])
        gcfg.BANK_SETS = [bs]
        rl._reload([path])

        assert gcfg.BANK_SETS[0]._display_fn == called.append
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
