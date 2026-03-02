"""Data types for the Tripswitch SDK."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType


class Latency:
    """Sentinel value for automatic latency measurement.

    Pass the **class itself** as a metric value to auto-measure task duration
    in milliseconds::

        ts.execute(task, metrics={"latency": Latency}, router="my-router")
    """

    def __new__(cls) -> Latency:  # noqa: PYI034
        raise TypeError(
            "Latency is a sentinel — use the class directly, not Latency()"
        )


@dataclass(frozen=True)
class BreakerStatus:
    """Cached state of a circuit breaker."""

    name: str
    state: str  # "open", "closed", "half_open"
    allow_rate: float = 0.0


@dataclass(frozen=True)
class BreakerMeta:
    """Breaker identity and user-defined metadata for dynamic selection."""

    id: str
    name: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(self.metadata))


@dataclass(frozen=True)
class RouterMeta:
    """Router identity and user-defined metadata for dynamic selection."""

    id: str
    name: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(self.metadata))


@dataclass(frozen=True)
class Status:
    """Project health summary from the API."""

    open_count: int
    closed_count: int
    last_eval_ms: int | None = None


@dataclass
class SDKStats:
    """Snapshot of SDK health metrics."""

    dropped_samples: int = 0
    buffer_size: int = 0
    sse_connected: bool = False
    sse_reconnects: int = 0
    last_successful_flush: datetime | None = None
    last_sse_event: datetime | None = None
    flush_failures: int = 0
    cached_breakers: int = 0
