"""
test_osc_integration.py

Integration tests for the OSC send type: real UDP packets sent and
received on localhost using python-osc.

The entire module is skipped when python-osc is not installed.  All
tests bind to port 0 (OS-assigned ephemeral port) to avoid conflicts.

These tests complement the unit tests in test_osc_ctrl.py:

    test_osc_ctrl.py        -- osc_ctrl.py internals, no real network I/O
    test_osc_integration.py -- real UDP round-trip through the full stack

Because a real osc_ctrl client is used here (not mocked), osc_ctrl._clients
is reset between tests to prevent state leakage.
"""
import threading
import time

import pytest

pythonosc = pytest.importorskip(
    "pythonosc",
    reason="python-osc not installed; skipping integration tests",
)

from pythonosc.dispatcher       import Dispatcher
from pythonosc.osc_server       import ThreadingOSCUDPServer

from midi_event_remapper.testing import make_bankset, make_pc, make_cc, make_note

from midi_event_remapper import osc_ctrl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_osc_pool(monkeypatch):
    """Clear the osc_ctrl client pool before each test.

    Uses monkeypatch so it is restored correctly even on failure, and so
    the package attribute stays consistent (same object, cleared contents).
    """
    monkeypatch.setattr(osc_ctrl, "_clients", {})


@pytest.fixture
def osc_listener():
    """Start a real ThreadingOSCUDPServer on an ephemeral port.

    Yields ``(port, received)`` where ``received`` is a list that grows
    as messages arrive.  Each entry is ``(address, args_list)``.

    The server shuts down cleanly after each test.
    """
    received = []

    dispatcher = Dispatcher()
    dispatcher.set_default_handler(
        lambda address, *args: received.append((address, list(args)))
    )

    server = ThreadingOSCUDPServer(("127.0.0.1", 0), dispatcher)
    port   = server.server_address[1]

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    yield port, received

    server.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SETTLE = 0.15   # seconds to wait for UDP round-trip on localhost


# ---------------------------------------------------------------------------
# Basic send
# ---------------------------------------------------------------------------

class TestRealSend:

    def test_no_args_message_arrives(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/ping"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert len(received) == 1
        assert received[0] == ("/ping", [])

    def test_single_int_arg_arrives(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/v", "args": [42]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert received[0] == ("/v", [42])

    def test_single_float_arg_arrives(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/f", "args": [0.5]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert received[0][0] == "/f"
        assert abs(received[0][1][0] - 0.5) < 1e-5

    def test_single_string_arg_arrives(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/s", "args": ["hello"]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert received[0] == ("/s", ["hello"])

    def test_multiple_args_arrive(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/multi", "args": [1, 2, 3]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert received[0] == ("/multi", [1, 2, 3])

    def test_mixed_type_args_arrive(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/mixed", "args": [7, 0.25, "ch1"]}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        addr, args = received[0]
        assert addr    == "/mixed"
        assert args[0] == 7
        assert abs(args[1] - 0.25) < 1e-5
        assert args[2] == "ch1"

    def test_address_forwarded_exactly(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/deep/nested/path"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert received[0][0] == "/deep/nested/path"

    def test_only_one_message_per_trigger(self, osc_listener, fake_timer):
        """Pressing a key once must send exactly one OSC message."""
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/once"}],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert len(received) == 1

    def test_two_triggers_send_two_messages(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/count"}],
        }})
        bs.handle(make_pc(5))
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert len(received) == 2


# ---------------------------------------------------------------------------
# Client pooling verified end-to-end
# ---------------------------------------------------------------------------

class TestClientPoolIntegration:

    def test_same_target_reuses_client(self, osc_listener, fake_timer):
        """Two sends to the same target must use the same client object."""
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/a"}],
            "PC6": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                     "address": "/b"}],
        }})
        bs.handle(make_pc(5))
        bs.handle(make_pc(6))
        time.sleep(SETTLE)
        assert len(received)          == 2
        assert len(osc_ctrl._clients) == 1   # one client for one target

    def test_different_targets_use_different_clients(self, fake_timer):
        """Two distinct ports must produce two distinct client objects."""
        # Start two separate servers.
        disp = Dispatcher()
        disp.set_default_handler(lambda *a: None)
        srv_a = ThreadingOSCUDPServer(("127.0.0.1", 0), disp)
        srv_b = ThreadingOSCUDPServer(("127.0.0.1", 0), disp)
        port_a, port_b = srv_a.server_address[1], srv_b.server_address[1]
        for srv in (srv_a, srv_b):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

        try:
            bs, _ = make_bankset({"default": {
                "PC5": [
                    {"send": "OSC", "host": "127.0.0.1", "port": port_a,
                     "address": "/a"},
                    {"send": "OSC", "host": "127.0.0.1", "port": port_b,
                     "address": "/b"},
                ],
            }})
            bs.handle(make_pc(5))
            time.sleep(SETTLE)
            assert len(osc_ctrl._clients) == 2
        finally:
            srv_a.shutdown()
            srv_b.shutdown()


# ---------------------------------------------------------------------------
# Combined sequences
# ---------------------------------------------------------------------------

class TestCombinedSequences:

    def test_osc_and_midi_in_same_sequence(self, osc_listener, fake_timer):
        """OSC send in a sequence with a MIDI send: both fire, MIDI returned."""
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [
                {"send": "CC10", "value": 127},
                {"send": "OSC", "host": "127.0.0.1", "port": port,
                 "address": "/trigger"},
            ],
        }})
        result = bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert len(result)   == 1
        assert result[0].ctrl == 10
        assert len(received) == 1

    def test_multiple_osc_in_sequence(self, osc_listener, fake_timer):
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "PC5": [
                {"send": "OSC", "host": "127.0.0.1", "port": port,
                 "address": "/first",  "args": [1]},
                {"send": "OSC", "host": "127.0.0.1", "port": port,
                 "address": "/second", "args": [2]},
            ],
        }})
        bs.handle(make_pc(5))
        time.sleep(SETTLE)
        assert len(received) == 2
        addresses = [r[0] for r in received]
        assert "/first"  in addresses
        assert "/second" in addresses

    def test_osc_on_gesture_single_double(self, osc_listener, fake_timer):
        """OSC send on single vs double: timer fires the correct branch."""
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "CC0": {
                "single": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                             "address": "/tap"}],
                "double": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                             "address": "/dtap"}],
            },
        }})
        # One press then let the multi-press window expire -> single
        bs.handle(make_cc(0, value=127))
        fake_timer.active()[0].fire()   # expire the multi-press window
        time.sleep(SETTLE)
        assert len(received) == 1
        assert received[0][0] == "/tap"

    def test_osc_on_toggle(self, osc_listener, fake_timer):
        """OSC send inside a toggle alternates correctly."""
        port, received = osc_listener
        bs, _ = make_bankset({"default": {
            "CC1": {
                "a": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                        "address": "/on",  "args": [1]}],
                "b": [{"send": "OSC", "host": "127.0.0.1", "port": port,
                        "address": "/off", "args": [0]}],
            },
        }})
        bs.handle(make_cc(1, value=127))   # → "a" → /on
        time.sleep(SETTLE)
        bs.handle(make_cc(1, value=127))   # → "b" → /off
        time.sleep(SETTLE)
        assert received[0] == ("/on",  [1])
        assert received[1] == ("/off", [0])


# ---------------------------------------------------------------------------
# Missing python-osc error message
# ---------------------------------------------------------------------------

class TestMissingPythonosc:

    def test_missing_pythonosc_prints_clear_error(
            self, monkeypatch, fake_timer, capsys):
        """When python-osc is not installed the error is always printed,
        regardless of the debug flag."""
        import sys

        # Temporarily hide pythonosc so _get_client raises ModuleNotFoundError.
        monkeypatch.setitem(sys.modules, "pythonosc.udp_client", None)
        # Also clear the client pool so the import is attempted fresh.
        monkeypatch.setattr(osc_ctrl, "_clients", {})

        bs, _ = make_bankset({"default": {
            "PC5": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                     "address": "/test"}],
        }})
        bs._debug = False   # confirm error prints even without debug
        bs.handle(make_pc(5))
        time.sleep(SETTLE)

        captured = capsys.readouterr()
        assert "python-osc" in captured.out
        assert "pip install python-osc" in captured.out
