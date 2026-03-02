"""Exception hierarchy for the Tripswitch SDK."""

from __future__ import annotations


class TripSwitchError(Exception):
    """Base exception for all Tripswitch errors."""


class BreakerOpenError(TripSwitchError):
    """Raised when a circuit breaker is open and the request is rejected.

    In half-open state, this may also be raised probabilistically based
    on the breaker's allow rate.
    """

    def __init__(self, breaker: str | None = None):
        self.breaker = breaker
        msg = f"breaker is open: {breaker}" if breaker else "breaker is open"
        super().__init__(msg)


class ConflictingOptionsError(TripSwitchError):
    """Raised when mutually exclusive execute options are used together."""


class MetadataUnavailableError(TripSwitchError):
    """Raised when a selector needs metadata but the cache is empty."""


# ── API errors ───────────────────────────────────────────────────────────


class APIError(TripSwitchError):
    """Error response from the Tripswitch API."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "",
        request_id: str = "",
        body: bytes = b"",
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id
        self.body = body
        self.retry_after = retry_after


class NotFoundError(APIError):
    """404 Not Found."""


class UnauthorizedError(APIError):
    """401 Unauthorized."""


class ForbiddenError(APIError):
    """403 Forbidden."""


class RateLimitedError(APIError):
    """429 Too Many Requests."""


class ConflictError(APIError):
    """409 Conflict."""


class ValidationError(APIError):
    """400 or 422 validation error."""


class TransportError(TripSwitchError):
    """Network or transport-level failure."""


class ServerFaultError(APIError):
    """5xx server error."""
