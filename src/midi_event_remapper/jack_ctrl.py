"""jack_ctrl.py

Persistent JACK client for transport control actions.

A single ``jack.Client("midi_remapper_ctrl")`` is created on first use and
kept alive for the lifetime of the process.  This is used by the
``JACK_TRANSPORT`` send type in BankSet sequences.

Why a persistent client rather than ``subprocess.run("jack_transport ...")``
----------------------------------------------------------------------------
Spawning a subprocess (``fork`` + ``exec``) forces the kernel to copy the
parent process's page tables and can cause memory pressure across the whole
system.  In a JACK real-time session this is enough to push other clients
past their deadline, causing xruns -- even when the spawned process itself
is harmless and exits quickly.

Using a persistent ``jack.Client`` avoids ``fork``/``exec`` entirely.
Transport functions (``transport_locate``, ``transport_start``,
``transport_stop``) write directly to JACK's shared-memory transport state
via the C library.  The call takes microseconds and does not disturb any
other client's scheduling.

The client is **not activated** (no audio or MIDI ports, no process
callback).  Activation is not required for transport control; it would
only add unnecessary overhead.

Thread safety
-------------
``jack.Client`` transport calls are safe to call from any thread.  The
lazy-initialization lock is only taken once (on first use); subsequent
calls are lock-free.

Failure handling
-----------------
If JACK is not running when the first call is made, ``jack.Client()``
raises ``jack.JackError``.  The caller (``BankSet._run_jack_transport``)
catches all exceptions and prints a debug message rather than crashing.
"""
import threading

_lock   = threading.Lock()
_client = None   # jack.Client instance, created on first use


def preinit():
    """Attempt to initialize the JACK client now, during loading.

    Called by BankSet._build_lookup_tables() when a JACK_TRANSPORT send
    is detected in the config.  Runs in the main thread before the
    dispatcher starts, so connection overhead does not occur mid-session.

    Safe to call when JACK is not running (e.g. during ``--validate``):
    errors are silently ignored and _get_client() will retry on first use.
    """
    try:
        _get_client()
    except Exception:
        pass


def _get_client():
    """Return the shared jack.Client, creating it on first call."""
    global _client
    # Fast path: client already exists.  No lock needed -- Python attribute
    # reads are atomic in CPython and we only ever write once.
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            import jack
            # no_start_server=True: fail fast if jackd is not running rather
            # than silently launching a new server instance.
            _client = jack.Client(
                "midi_remapper_ctrl",
                no_start_server=True,
            )
            # Do not call client.activate(): we only need transport control,
            # which does not require the client to have an active process
            # callback or registered ports.
    return _client


def transport_start():
    """Tell JACK to start rolling."""
    _get_client().transport_start()


def transport_stop():
    """Tell JACK to stop."""
    _get_client().transport_stop()


def transport_locate(frame: int):
    """Reposition JACK transport to *frame* (sample offset from time zero).

    Parameters
    ----------
    frame : int
        Target position in samples.  Pass ``0`` to rewind to the
        beginning.  The sample rate is whatever JACK is configured with;
        for example at 48 kHz, frame 48000 = 1 second.
    """
    _get_client().transport_locate(frame)
