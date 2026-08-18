"""
test_config.py

Tests for config.py helpers.  Currently just urgent_print(), whose whole
purpose is timing: with stdout redirected to a file Python block-buffers
it, so an unflushed message can sit unwritten indefinitely.
"""
import sys

from midi_event_remapper.config import urgent_print


class TestUrgentPrint:

    def test_writes_to_both_streams(self, capsys):
        """stdout keeps the ordered log; stderr reaches the console."""
        urgent_print("something went wrong")
        captured = capsys.readouterr()
        assert "something went wrong" in captured.out
        assert "something went wrong" in captured.err

    def test_flushes_stdout(self, monkeypatch):
        """The flush is the point.  Without it the message stays in the
        8 KB buffer, which with debug off can take days to fill."""

        class _Recorder:
            def __init__(self):
                self.text    = ""
                self.flushed = False

            def write(self, s):
                self.text += s

            def flush(self):
                self.flushed = True

        rec = _Recorder()
        monkeypatch.setattr(sys, "stdout", rec)
        urgent_print("urgent")
        assert "urgent" in rec.text
        assert rec.flushed is True

    def test_plain_print_is_not_flushed(self, monkeypatch):
        """Guard against the opposite mistake: ordinary tracing must stay
        buffered, or the RT callback pays a syscall per line."""

        class _Recorder:
            def __init__(self):
                self.flushed = False

            def write(self, s):
                pass

            def flush(self):
                self.flushed = True

        rec = _Recorder()
        monkeypatch.setattr(sys, "stdout", rec)
        print("ordinary tracing")
        assert rec.flushed is False
