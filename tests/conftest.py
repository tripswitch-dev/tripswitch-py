"""Shared test helpers for the Tripswitch SDK test suite."""

from __future__ import annotations

import tripswitch
from tripswitch.client import Client, _BreakerState


def make_client(**kwargs) -> Client:
    """Create a client with SSE/flusher/metadata-sync disabled for unit tests."""
    c = Client.__new__(Client)
    # Call __init__ with defaults, then override internals
    Client.__init__(c, "test-project", **kwargs)
    # Prevent background threads from starting
    c._connected = True
    return c


def set_breaker_state(
    client: Client, name: str, state: str, allow_rate: float = 0.0
) -> None:
    """Inject a breaker state into the client's cache."""
    with client._states_lock:
        client._states[name] = _BreakerState(state=state, allow_rate=allow_rate)
