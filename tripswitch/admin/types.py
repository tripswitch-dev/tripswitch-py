"""Data types for the Tripswitch admin API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any


# ── Enums ────────────────────────────────────────────────────────────────


class BreakerKind(str, Enum):
    """Aggregation type for a breaker."""

    ERROR_RATE = "error_rate"
    AVG = "avg"
    P95 = "p95"
    MAX = "max"
    MIN = "min"
    SUM = "sum"
    STDDEV = "stddev"
    COUNT = "count"
    PERCENTILE = "percentile"
    CONSECUTIVE_FAILURES = "consecutive_failures"
    DELTA = "delta"


class BreakerOp(str, Enum):
    """Comparison operator for a breaker threshold."""

    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"


class HalfOpenPolicy(str, Enum):
    """Policy for half-open state when data is insufficient."""

    OPTIMISTIC = "optimistic"
    CONSERVATIVE = "conservative"
    PESSIMISTIC = "pessimistic"


class RouterMode(str, Enum):
    """Routing mode for a router."""

    STATIC = "static"
    CANARY = "canary"
    WEIGHTED = "weighted"


class NotificationChannelType(str, Enum):
    """Type of notification channel."""

    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    EMAIL = "email"
    WEBHOOK = "webhook"


class NotificationEventType(str, Enum):
    """Event types that trigger notifications."""

    TRIP = "trip"
    RECOVER = "recover"


# ── Request options ──────────────────────────────────────────────────────


@dataclass
class RequestOptions:
    """Per-request options for admin API calls.

    ::

        from tripswitch.admin import RequestOptions

        client.create_breaker(
            "proj_abc", spec,
            options=RequestOptions(idempotency_key="abc-123", timeout=10),
        )
    """

    idempotency_key: str | None = None
    timeout: float | None = None
    request_id: str | None = None
    headers: dict[str, str] | None = None


# ── Pagination ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ListParams:
    """Common pagination parameters."""

    cursor: str | None = None
    limit: int = 0


# ── Workspaces ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Workspace:
    """A Tripswitch workspace."""

    id: str
    name: str
    slug: str
    org_id: str = ""
    inserted_at: datetime | None = None

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> Workspace:
        # The workspace API consistently uses "id" — no "workspace_id"
        # dual-key unlike the project API (which returns "project_id").
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            org_id=d.get("org_id", ""),
            inserted_at=_parse_dt(d, "inserted_at"),
        )


@dataclass
class CreateWorkspaceInput:
    """Fields for creating a workspace."""

    name: str
    slug: str

    def _to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "slug": self.slug}


@dataclass
class UpdateWorkspaceInput:
    """Fields for updating a workspace.  Only set fields are sent."""

    name: str | None = None
    slug: str | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        _set_optional(d, "name", self.name)
        _set_optional(d, "slug", self.slug)
        return d


@dataclass(frozen=True)
class ListWorkspacesResponse:
    """Response from listing workspaces.

    Unlike :class:`ListProjectsResponse`, the workspace list endpoint does
    not return a ``count`` field — this matches the upstream API spec.
    """

    workspaces: tuple[Workspace, ...]

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> ListWorkspacesResponse:
        return cls(
            workspaces=tuple(
                Workspace._from_dict(w) for w in d.get("workspaces", [])
            ),
        )


# ── Projects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Project:
    """A Tripswitch project."""

    id: str
    name: str
    slack_webhook_url: str = ""
    trace_id_url_template: str = ""
    enable_signed_ingest: bool = False
    workspace_id: str = ""

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> Project:
        return cls(
            id=d.get("project_id", d.get("id", "")),
            name=d.get("name", ""),
            slack_webhook_url=d.get("slack_webhook_url", ""),
            trace_id_url_template=d.get("trace_id_url_template", ""),
            enable_signed_ingest=d.get("enable_signed_ingest", False),
            workspace_id=d.get("workspace_id", ""),
        )


@dataclass
class CreateProjectInput:
    """Fields for creating a project."""

    name: str
    workspace_id: str | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        _set_optional(d, "workspace_id", self.workspace_id)
        return d


@dataclass(frozen=True)
class ListProjectsResponse:
    """Response from listing projects."""

    projects: tuple[Project, ...]
    count: int = 0

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> ListProjectsResponse:
        return cls(
            projects=tuple(
                Project._from_dict(p) for p in d.get("projects", [])
            ),
            count=d.get("count", 0),
        )


@dataclass
class UpdateProjectInput:
    """Fields for updating a project.  Only set fields are sent."""

    name: str | None = None
    slack_webhook_url: str | None = None
    trace_id_url_template: str | None = None
    enable_signed_ingest: bool | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        _set_optional(d, "name", self.name)
        _set_optional(d, "slack_webhook_url", self.slack_webhook_url)
        _set_optional(d, "trace_id_url_template", self.trace_id_url_template)
        _set_optional(d, "enable_signed_ingest", self.enable_signed_ingest)
        return d


@dataclass(frozen=True)
class IngestSecretRotation:
    """Result of rotating an ingest secret."""

    ingest_secret: str

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> IngestSecretRotation:
        return cls(ingest_secret=d["ingest_secret"])


# ── Breakers ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Breaker:
    """A circuit breaker configuration."""

    id: str
    name: str
    metric: str
    kind: BreakerKind
    op: BreakerOp
    threshold: float
    router_id: str = ""
    kind_params: Mapping[str, Any] = field(default_factory=dict)
    window_ms: int = 0
    min_count: int = 0
    min_state_duration_ms: int = 0
    cooldown_ms: int = 0
    eval_interval_ms: int = 0
    half_open_confirmation_ms: int = 0
    half_open_backoff_enabled: bool = False
    half_open_backoff_cap_ms: int = 0
    half_open_indeterminate_policy: HalfOpenPolicy | None = None
    recovery_window_ms: int = 0
    recovery_allow_rate_ramp_steps: int = 0
    actions: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("kind_params", "actions", "metadata"):
            val = getattr(self, attr)
            if not isinstance(val, MappingProxyType):
                object.__setattr__(self, attr, MappingProxyType(val))

    @classmethod
    def _from_dict(cls, d: dict[str, Any], router_id: str = "") -> Breaker:
        kind_raw = d.get("kind", "")
        op_raw = d.get("op", "")
        hop_raw = d.get("half_open_indeterminate_policy")
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            metric=d.get("metric", ""),
            kind=BreakerKind(kind_raw) if kind_raw else BreakerKind.ERROR_RATE,
            op=BreakerOp(op_raw) if op_raw else BreakerOp.GT,
            threshold=d.get("threshold", 0.0),
            router_id=router_id or d.get("router_id", ""),
            kind_params=d.get("kind_params") or {},
            window_ms=d.get("window_ms", 0),
            min_count=d.get("min_count", 0),
            min_state_duration_ms=d.get("min_state_duration_ms", 0),
            cooldown_ms=d.get("cooldown_ms", 0),
            eval_interval_ms=d.get("eval_interval_ms", 0),
            half_open_confirmation_ms=d.get("half_open_confirmation_ms", 0),
            half_open_backoff_enabled=d.get("half_open_backoff_enabled", False),
            half_open_backoff_cap_ms=d.get("half_open_backoff_cap_ms", 0),
            half_open_indeterminate_policy=(
                HalfOpenPolicy(hop_raw) if hop_raw else None
            ),
            recovery_window_ms=d.get("recovery_window_ms", 0),
            recovery_allow_rate_ramp_steps=d.get(
                "recovery_allow_rate_ramp_steps", 0
            ),
            actions=d.get("actions") or {},
            metadata=d.get("metadata") or {},
        )


@dataclass
class CreateBreakerInput:
    """Fields for creating a breaker."""

    name: str
    metric: str
    kind: BreakerKind
    op: BreakerOp
    threshold: float
    kind_params: dict[str, Any] | None = None
    window_ms: int | None = None
    min_count: int | None = None
    min_state_duration_ms: int | None = None
    cooldown_ms: int | None = None
    eval_interval_ms: int | None = None
    half_open_backoff_enabled: bool | None = None
    half_open_backoff_cap_ms: int | None = None
    half_open_indeterminate_policy: HalfOpenPolicy | None = None
    recovery_allow_rate_ramp_steps: int | None = None
    actions: dict[str, Any] | None = None
    metadata: dict[str, str] | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "metric": self.metric,
            "kind": self.kind,
            "op": self.op,
            "threshold": self.threshold,
        }
        _set_optional(d, "kind_params", self.kind_params)
        _set_optional(d, "window_ms", self.window_ms)
        _set_optional(d, "min_count", self.min_count)
        _set_optional(d, "min_state_duration_ms", self.min_state_duration_ms)
        _set_optional(d, "cooldown_ms", self.cooldown_ms)
        _set_optional(d, "eval_interval_ms", self.eval_interval_ms)
        _set_optional(d, "half_open_backoff_enabled", self.half_open_backoff_enabled)
        _set_optional(d, "half_open_backoff_cap_ms", self.half_open_backoff_cap_ms)
        _set_optional(
            d, "half_open_indeterminate_policy", self.half_open_indeterminate_policy
        )
        _set_optional(
            d, "recovery_allow_rate_ramp_steps", self.recovery_allow_rate_ramp_steps
        )
        _set_optional(d, "actions", self.actions)
        _set_optional(d, "metadata", self.metadata)
        return d


@dataclass
class UpdateBreakerInput:
    """Fields for updating a breaker.  Only set fields are sent."""

    name: str | None = None
    metric: str | None = None
    kind: BreakerKind | None = None
    kind_params: dict[str, Any] | None = None
    op: BreakerOp | None = None
    threshold: float | None = None
    window_ms: int | None = None
    min_count: int | None = None
    min_state_duration_ms: int | None = None
    cooldown_ms: int | None = None
    eval_interval_ms: int | None = None
    half_open_backoff_enabled: bool | None = None
    half_open_backoff_cap_ms: int | None = None
    half_open_indeterminate_policy: HalfOpenPolicy | None = None
    recovery_allow_rate_ramp_steps: int | None = None
    actions: dict[str, Any] | None = None
    metadata: dict[str, str] | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        _set_optional(d, "name", self.name)
        _set_optional(d, "metric", self.metric)
        _set_optional(d, "kind", self.kind)
        _set_optional(d, "kind_params", self.kind_params)
        _set_optional(d, "op", self.op)
        _set_optional(d, "threshold", self.threshold)
        _set_optional(d, "window_ms", self.window_ms)
        _set_optional(d, "min_count", self.min_count)
        _set_optional(d, "min_state_duration_ms", self.min_state_duration_ms)
        _set_optional(d, "cooldown_ms", self.cooldown_ms)
        _set_optional(d, "eval_interval_ms", self.eval_interval_ms)
        _set_optional(d, "half_open_backoff_enabled", self.half_open_backoff_enabled)
        _set_optional(d, "half_open_backoff_cap_ms", self.half_open_backoff_cap_ms)
        _set_optional(
            d, "half_open_indeterminate_policy", self.half_open_indeterminate_policy
        )
        _set_optional(
            d, "recovery_allow_rate_ramp_steps", self.recovery_allow_rate_ramp_steps
        )
        _set_optional(d, "actions", self.actions)
        _set_optional(d, "metadata", self.metadata)
        return d


@dataclass
class SyncBreakersInput:
    """Breaker definitions for bulk sync (replaces all breakers)."""

    breakers: list[CreateBreakerInput]

    def _to_dict(self) -> dict[str, Any]:
        return {"breakers": [b._to_dict() for b in self.breakers]}


@dataclass(frozen=True)
class BreakerState:
    """Current state of a circuit breaker (from admin API)."""

    breaker_id: str
    state: str  # "open", "closed", "half_open"
    allow_rate: float
    updated_at: datetime | None = None

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> BreakerState:
        return cls(
            breaker_id=d.get("breaker_id", ""),
            state=d.get("state", ""),
            allow_rate=d.get("allow_rate", 0.0),
            updated_at=_parse_dt(d, "updated_at"),
        )


@dataclass
class BatchGetBreakerStatesInput:
    """Parameters for retrieving multiple breaker states."""

    breaker_ids: list[str] | None = None
    router_id: str | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        _set_optional(d, "breaker_ids", self.breaker_ids)
        _set_optional(d, "router_id", self.router_id)
        return d


# ── Routers ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Router:
    """A router configuration."""

    id: str
    name: str
    mode: RouterMode
    enabled: bool
    breaker_count: int = 0
    breakers: tuple[Breaker, ...] = ()
    inserted_at: datetime | None = None
    created_by: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(self.metadata))

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> Router:
        mode_raw = d.get("mode", "static")
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            mode=RouterMode(mode_raw),
            enabled=d.get("enabled", False),
            breaker_count=d.get("breaker_count", 0),
            breakers=tuple(
                Breaker._from_dict(b) for b in (d.get("breakers") or [])
            ),
            inserted_at=_parse_dt(d, "inserted_at"),
            created_by=d.get("created_by", ""),
            metadata=d.get("metadata") or {},
        )


@dataclass
class CreateRouterInput:
    """Fields for creating a router."""

    name: str
    mode: RouterMode
    description: str | None = None
    enabled: bool = True
    metadata: dict[str, str] | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "mode": self.mode, "enabled": self.enabled}
        _set_optional(d, "description", self.description)
        _set_optional(d, "metadata", self.metadata)
        return d


@dataclass
class UpdateRouterInput:
    """Fields for updating a router.  Only set fields are sent."""

    name: str | None = None
    description: str | None = None
    mode: RouterMode | None = None
    enabled: bool | None = None
    metadata: dict[str, str] | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        _set_optional(d, "name", self.name)
        _set_optional(d, "description", self.description)
        _set_optional(d, "mode", self.mode)
        _set_optional(d, "enabled", self.enabled)
        _set_optional(d, "metadata", self.metadata)
        return d


@dataclass
class LinkBreakerInput:
    """Parameters for linking a breaker to a router."""

    breaker_id: str

    def _to_dict(self) -> dict[str, Any]:
        return {"breaker_id": self.breaker_id}


# ── Notification channels ────────────────────────────────────────────────


@dataclass(frozen=True)
class NotificationChannel:
    """A notification channel configuration."""

    id: str
    project_id: str
    name: str
    channel: NotificationChannelType
    config: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[NotificationEventType, ...] = ()
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config, MappingProxyType):
            object.__setattr__(self, "config", MappingProxyType(self.config))

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> NotificationChannel:
        return cls(
            id=d.get("id", ""),
            project_id=d.get("project_id", ""),
            name=d.get("name", ""),
            channel=NotificationChannelType(d.get("channel", "webhook")),
            config=d.get("config") or {},
            events=tuple(NotificationEventType(e) for e in (d.get("events") or [])),
            enabled=d.get("enabled", True),
            created_at=_parse_dt(d, "created_at"),
            updated_at=_parse_dt(d, "updated_at"),
        )


@dataclass
class CreateNotificationChannelInput:
    """Fields for creating a notification channel."""

    name: str
    channel: NotificationChannelType
    config: dict[str, Any]
    events: list[NotificationEventType]
    enabled: bool = True

    def _to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "channel": self.channel,
            "config": self.config,
            "events": [e.value for e in self.events],
            "enabled": self.enabled,
        }


@dataclass
class UpdateNotificationChannelInput:
    """Fields for updating a notification channel.  Only set fields are sent."""

    name: str | None = None
    config: dict[str, Any] | None = None
    events: list[NotificationEventType] | None = None
    enabled: bool | None = None

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        _set_optional(d, "name", self.name)
        _set_optional(d, "config", self.config)
        if self.events is not None:
            d["events"] = [e.value for e in self.events]
        _set_optional(d, "enabled", self.enabled)
        return d


# ── Events ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Event:
    """A breaker state transition event."""

    id: str
    project_id: str
    breaker_id: str
    from_state: str
    to_state: str
    timestamp: datetime | None = None
    reason: str = ""

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> Event:
        return cls(
            id=d.get("id", ""),
            project_id=d.get("project_id", ""),
            breaker_id=d.get("breaker_id", ""),
            from_state=d.get("from_state", ""),
            to_state=d.get("to_state", ""),
            reason=d.get("reason", ""),
            timestamp=_parse_dt(d, "timestamp"),
        )


@dataclass
class ListEventsParams:
    """Parameters for listing events."""

    breaker_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    cursor: str | None = None
    limit: int = 0


# ── Project keys ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectKey:
    """A project API key (eb_pk_...)."""

    id: str
    name: str
    key_prefix: str
    inserted_at: datetime | None = None
    last_used_at: datetime | None = None

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> ProjectKey:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            key_prefix=d.get("key_prefix", ""),
            inserted_at=_parse_dt(d, "inserted_at"),
            last_used_at=_parse_dt(d, "last_used_at"),
        )


@dataclass
class CreateProjectKeyInput:
    """Fields for creating a project key."""

    name: str = ""

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.name:
            d["name"] = self.name
        return d


@dataclass(frozen=True)
class CreateProjectKeyResponse:
    """Response from creating a project key.

    The ``key`` field contains the full API key and is only returned on
    creation.  Store it securely — it cannot be retrieved later.
    """

    id: str
    name: str
    key: str
    key_prefix: str
    message: str = ""

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> CreateProjectKeyResponse:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            key=d.get("key", ""),
            key_prefix=d.get("key_prefix", ""),
            message=d.get("message", ""),
        )


# ── Helpers ──────────────────────────────────────────────────────────────


def _set_optional(d: dict[str, Any], key: str, value: Any) -> None:
    """Add *value* to *d* under *key* only if it is not ``None``."""
    if value is not None:
        d[key] = value


def _parse_dt(d: dict[str, Any], key: str) -> datetime | None:
    """Parse an ISO-8601 datetime from *d[key]*, returning ``None`` on failure."""
    raw = d.get(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
