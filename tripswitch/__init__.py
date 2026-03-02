"""Tripswitch — Official Python SDK for the Tripswitch circuit breaker service.

Quick start::

    import tripswitch

    with tripswitch.Client(
        "proj_abc123",
        api_key="eb_pk_...",
        ingest_secret="64-char-hex",
    ) as ts:
        result = ts.execute(
            my_task,
            breakers=["checkout-latency"],
            router="checkout-router",
            metrics={"latency": tripswitch.Latency},
        )
"""

from tripswitch.client import CLIENT_VERSION as __version__  # noqa: F401 — re-export
from tripswitch.client import CONTRACT_VERSION, Client
from tripswitch.errors import (
    APIError,
    BreakerOpenError,
    ConflictError,
    ConflictingOptionsError,
    ForbiddenError,
    MetadataUnavailableError,
    NotFoundError,
    RateLimitedError,
    ServerFaultError,
    TransportError,
    TripSwitchError,
    UnauthorizedError,
    ValidationError,
)
from tripswitch.types import (
    BreakerMeta,
    BreakerStatus,
    Latency,
    RouterMeta,
    SDKStats,
    Status,
)

__all__ = [
    # Client
    "Client",
    "CONTRACT_VERSION",
    # Sentinel
    "Latency",
    # Types
    "BreakerMeta",
    "BreakerStatus",
    "RouterMeta",
    "SDKStats",
    "Status",
    # Errors
    "APIError",
    "BreakerOpenError",
    "ConflictError",
    "ConflictingOptionsError",
    "ForbiddenError",
    "MetadataUnavailableError",
    "NotFoundError",
    "RateLimitedError",
    "ServerFaultError",
    "TransportError",
    "TripSwitchError",
    "UnauthorizedError",
    "ValidationError",
]
