"""Tripswitch admin API client.

::

    from tripswitch.admin import AdminClient, CreateBreakerInput, BreakerKind, BreakerOp

    client = AdminClient(api_key="eb_admin_...")
    breaker = client.create_breaker(
        "proj_abc123",
        CreateBreakerInput(
            name="api-latency",
            metric="latency_ms",
            kind=BreakerKind.P95,
            op=BreakerOp.GT,
            threshold=500,
        ),
    )
"""

from tripswitch.admin.client import AdminClient
from tripswitch.admin.types import (
    BatchGetBreakerStatesInput,
    Breaker,
    BreakerKind,
    BreakerOp,
    BreakerState,
    CreateBreakerInput,
    CreateNotificationChannelInput,
    CreateProjectInput,
    CreateProjectKeyInput,
    CreateProjectKeyResponse,
    CreateRouterInput,
    Event,
    HalfOpenPolicy,
    IngestSecretRotation,
    LinkBreakerInput,
    ListEventsParams,
    ListParams,
    NotificationChannel,
    NotificationChannelType,
    NotificationEventType,
    Project,
    ProjectKey,
    RequestOptions,
    Router,
    RouterMode,
    SyncBreakersInput,
    UpdateBreakerInput,
    UpdateNotificationChannelInput,
    UpdateProjectInput,
    UpdateRouterInput,
)

__all__ = [
    # Client
    "AdminClient",
    # Enums
    "BreakerKind",
    "BreakerOp",
    "HalfOpenPolicy",
    "RouterMode",
    "NotificationChannelType",
    "NotificationEventType",
    # Output types
    "Breaker",
    "BreakerState",
    "Event",
    "IngestSecretRotation",
    "NotificationChannel",
    "Project",
    "ProjectKey",
    "Router",
    "CreateProjectKeyResponse",
    "RequestOptions",
    # Input types
    "BatchGetBreakerStatesInput",
    "CreateBreakerInput",
    "CreateNotificationChannelInput",
    "CreateProjectInput",
    "CreateProjectKeyInput",
    "CreateRouterInput",
    "LinkBreakerInput",
    "ListEventsParams",
    "ListParams",
    "SyncBreakersInput",
    "UpdateBreakerInput",
    "UpdateNotificationChannelInput",
    "UpdateProjectInput",
    "UpdateRouterInput",
]
