"""osc_ctrl.py

Pool of outgoing OSC clients for the ``OSC`` send type.

One ``SimpleUDPClient`` is created per ``(host, port)`` target on first use
and kept alive for the lifetime of the process.  All targets found in the
config are pre-initialized during loading (via ``preinit``) so that UDP
socket creation does not occur at action time.

Thread safety
-------------
``_get_client`` uses a standard double-checked lock for the initial
creation of each client.  Once a client exists in ``_clients`` the fast
path is lock-free: dict reads are atomic in CPython and each key is only
written once.  ``SimpleUDPClient.send_message`` calls ``socket.sendto``
which is a single syscall and is GIL-safe from any thread.

python-osc argument conventions
--------------------------------
``send_message(address, value)`` in python-osc accepts:

* ``None``          -- no-argument OSC message
* a scalar          -- single typed argument (int / float / str / bytes)
* a list            -- each element becomes one typed argument

We normalize from the config ``"args"`` list accordingly:

* ``[]`` / omitted  → ``None``   (no arguments)
* ``[x]``           → ``x``      (single argument)
* ``[x, y, ...]``   → ``[x, y, ...]``  (multiple arguments)
"""
import threading

_lock    = threading.Lock()
_clients = {}   # (host, port) -> SimpleUDPClient


def _get_client(host: str, port: int):
    """Return the ``SimpleUDPClient`` for ``(host, port)``, creating it if needed."""
    key = (host, port)
    # Fast path: already created.  Dict reads are atomic in CPython.
    if key in _clients:
        return _clients[key]
    with _lock:
        if key not in _clients:
            from pythonosc.udp_client import SimpleUDPClient
            _clients[key] = SimpleUDPClient(host, port)
    return _clients[key]


def preinit(host: str, port: int) -> None:
    """Pre-create the client for ``(host, port)`` during config loading.

    Called by ``BankSet._build_lookup_tables`` when an ``OSC`` send action
    is found.  Errors (e.g. bad host format) are silently swallowed here;
    they will surface as an exception in ``send`` when the action fires.
    """
    try:
        _get_client(host, port)
    except Exception:
        pass


def send(host: str, port: int, address: str, args: list) -> None:
    """Send an OSC message to ``host:port``.

    Parameters
    ----------
    host    : str   -- destination hostname or IP address
    port    : int   -- destination UDP port
    address : str   -- OSC address string, e.g. ``"/transport/locate"``
    args    : list  -- argument values (int, float, or str elements).
                       An empty list sends a no-argument message.
    """
    client = _get_client(host, port)
    if not args:
        client.send_message(address, None)
    elif len(args) == 1:
        client.send_message(address, args[0])
    else:
        client.send_message(address, args)
