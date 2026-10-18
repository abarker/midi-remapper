"""
test_osc_ctrl.py

Unit tests for osc_ctrl.py.

python-osc is NOT required.  ``pythonosc.udp_client.SimpleUDPClient`` is
replaced with a lightweight recording stub injected into ``sys.modules``
before any call that would trigger the lazy import inside ``_get_client``.

What these tests cover that the bankset-level mock tests (TestOscSend) do not:
- Arg normalization: [] -> None, [x] -> scalar, [x,y,...] -> list
- Client pooling: same (host, port) returns the same object
- Separate targets get separate clients
- preinit() silently swallows exceptions (e.g. pythonosc not installed)
- send() reaches send_message() on the right client with the right value
"""
import sys
import types
import pytest
from midi_event_remapper import osc_ctrl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeClient:
    """Recording stand-in for SimpleUDPClient."""
    def __init__(self, host, port):
        self.host  = host
        self.port  = port
        self.calls = []   # list of (address, value) tuples

    def send_message(self, address, value):
        self.calls.append((address, value))


@pytest.fixture(autouse=True)
def reset_osc_pool(monkeypatch):
    """Clear the client pool before each test to prevent state leakage."""
    monkeypatch.setattr(osc_ctrl, "_clients", {})


@pytest.fixture
def fake_pythonosc(monkeypatch):
    """Inject a mock pythonosc.udp_client into sys.modules.

    Returns the list of _FakeClient instances created during the test so
    callers can inspect what was constructed and what was sent.
    """
    created = []

    class _TrackingClient(_FakeClient):
        def __init__(self, host, port):
            super().__init__(host, port)
            created.append(self)

    mock_udp_mod = types.SimpleNamespace(SimpleUDPClient=_TrackingClient)
    monkeypatch.setitem(sys.modules, "pythonosc",             mock_udp_mod)
    monkeypatch.setitem(sys.modules, "pythonosc.udp_client",  mock_udp_mod)
    return created


# ---------------------------------------------------------------------------
# Arg normalization
# ---------------------------------------------------------------------------

class TestArgNormalization:
    """osc_ctrl.send() must convert args list to the form python-osc expects."""

    def test_empty_args_sends_none(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/ping", [])
        assert fake_pythonosc[0].calls == [("/ping", None)]

    def test_no_arg_message_explicit_empty(self, fake_pythonosc):
        """Empty list and completely absent args both result in None."""
        osc_ctrl.send("127.0.0.1", 9000, "/ping", [])
        osc_ctrl.send("127.0.0.1", 9000, "/ping", [])   # reuses same client
        assert all(v is None for _, v in fake_pythonosc[0].calls)

    def test_single_int_sends_scalar(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/v", [42])
        _, value = fake_pythonosc[0].calls[0]
        assert value == 42
        assert not isinstance(value, list)

    def test_single_float_sends_scalar(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/v", [0.75])
        _, value = fake_pythonosc[0].calls[0]
        assert value == 0.75
        assert not isinstance(value, list)

    def test_single_string_sends_scalar(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/v", ["hello"])
        _, value = fake_pythonosc[0].calls[0]
        assert value == "hello"
        assert not isinstance(value, list)

    def test_multiple_args_sends_list(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/v", [1, 2.0, "x"])
        _, value = fake_pythonosc[0].calls[0]
        assert value == [1, 2.0, "x"]
        assert isinstance(value, list)

    def test_two_args_sends_list(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/v", [10, 20])
        _, value = fake_pythonosc[0].calls[0]
        assert value == [10, 20]

    def test_address_forwarded_correctly(self, fake_pythonosc):
        osc_ctrl.send("127.0.0.1", 9000, "/some/deep/path", [1])
        address, _ = fake_pythonosc[0].calls[0]
        assert address == "/some/deep/path"


# ---------------------------------------------------------------------------
# Client pooling
# ---------------------------------------------------------------------------

class TestClientPool:
    """_get_client() must return the same object for the same (host, port)."""

    def test_same_target_returns_same_client(self, fake_pythonosc):
        c1 = osc_ctrl._get_client("127.0.0.1", 9000)
        c2 = osc_ctrl._get_client("127.0.0.1", 9000)
        assert c1 is c2

    def test_same_target_creates_one_client(self, fake_pythonosc):
        osc_ctrl._get_client("127.0.0.1", 9000)
        osc_ctrl._get_client("127.0.0.1", 9000)
        assert len(fake_pythonosc) == 1

    def test_different_port_different_client(self, fake_pythonosc):
        c1 = osc_ctrl._get_client("127.0.0.1", 9000)
        c2 = osc_ctrl._get_client("127.0.0.1", 9001)
        assert c1 is not c2
        assert len(fake_pythonosc) == 2

    def test_different_host_different_client(self, fake_pythonosc):
        c1 = osc_ctrl._get_client("127.0.0.1", 9000)
        c2 = osc_ctrl._get_client("10.0.0.5",  9000)
        assert c1 is not c2

    def test_client_constructed_with_correct_host_port(self, fake_pythonosc):
        osc_ctrl._get_client("10.0.0.5", 7400)
        assert fake_pythonosc[0].host == "10.0.0.5"
        assert fake_pythonosc[0].port == 7400

    def test_send_routes_to_correct_client(self, fake_pythonosc):
        """Two different targets must each receive only their own messages."""
        osc_ctrl.send("127.0.0.1", 9000, "/a", [1])
        osc_ctrl.send("10.0.0.5",  9001, "/b", [2])
        client_a = next(c for c in fake_pythonosc if c.port == 9000)
        client_b = next(c for c in fake_pythonosc if c.port == 9001)
        assert client_a.calls == [("/a", 1)]
        assert client_b.calls == [("/b", 2)]


# ---------------------------------------------------------------------------
# preinit
# ---------------------------------------------------------------------------

class TestPreinit:
    """preinit() must create the client when pythonosc is available, and
    must silently swallow all exceptions when it is not."""

    def test_preinit_creates_client(self, fake_pythonosc):
        osc_ctrl.preinit("127.0.0.1", 9000)
        assert len(osc_ctrl._clients) == 1
        assert ("127.0.0.1", 9000) in osc_ctrl._clients

    def test_preinit_multiple_targets(self, fake_pythonosc):
        osc_ctrl.preinit("127.0.0.1", 9000)
        osc_ctrl.preinit("10.0.0.5",  7400)
        assert len(osc_ctrl._clients) == 2

    def test_preinit_idempotent(self, fake_pythonosc):
        osc_ctrl.preinit("127.0.0.1", 9000)
        osc_ctrl.preinit("127.0.0.1", 9000)
        assert len(fake_pythonosc) == 1   # client created only once

    def test_preinit_no_pythonosc_does_not_raise(self, monkeypatch):
        """preinit() must be silent when pythonosc is not installed."""
        monkeypatch.setitem(sys.modules, "pythonosc.udp_client", None)
        osc_ctrl.preinit("127.0.0.1", 9000)   # must not raise

    def test_preinit_other_exception_does_not_raise(self, monkeypatch):
        """preinit() must swallow any exception from client construction."""
        broken = types.SimpleNamespace(
            SimpleUDPClient=lambda h, p: (_ for _ in ()).throw(
                RuntimeError("socket error")
            )
        )
        monkeypatch.setitem(sys.modules, "pythonosc",            broken)
        monkeypatch.setitem(sys.modules, "pythonosc.udp_client", broken)
        osc_ctrl.preinit("127.0.0.1", 9000)   # must not raise
