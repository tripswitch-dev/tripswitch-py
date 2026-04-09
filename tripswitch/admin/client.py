"""Tripswitch admin API client."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from tripswitch.errors import (
    APIError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ServerFaultError,
    TransportError,
    UnauthorizedError,
    ValidationError,
)
from tripswitch.admin.types import (
    BatchGetBreakerStatesInput,
    Breaker,
    BreakerState,
    CreateBreakerInput,
    CreateNotificationChannelInput,
    CreateProjectInput,
    CreateProjectKeyInput,
    CreateProjectKeyResponse,
    CreateRouterInput,
    CreateWorkspaceInput,
    Event,
    IngestSecretRotation,
    LinkBreakerInput,
    ListEventsParams,
    ListParams,
    ListProjectsResponse,
    ListWorkspacesResponse,
    NotificationChannel,
    Project,
    ProjectKey,
    RequestOptions,
    Router,
    SyncBreakersInput,
    UpdateBreakerInput,
    UpdateNotificationChannelInput,
    UpdateProjectInput,
    UpdateRouterInput,
    UpdateWorkspaceInput,
    Workspace,
)

_DEFAULT_BASE_URL = "https://api.tripswitch.dev"
_DEFAULT_TIMEOUT = 30.0


class AdminClient:
    """Client for the Tripswitch management API.

    Requires an admin API key (``eb_admin_...``) which is org-scoped::

        from tripswitch.admin import AdminClient

        client = AdminClient(api_key="eb_admin_...")
        project = client.get_project("proj_abc123")
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> AdminClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Workspaces ────────────────────────────────────────────────────────

    def list_workspaces(
        self, *, options: RequestOptions | None = None,
    ) -> ListWorkspacesResponse:
        """List all workspaces in the org."""
        data = self._do("GET", "/v1/workspaces", options=options)
        return ListWorkspacesResponse._from_dict(data)

    def create_workspace(
        self, workspace: CreateWorkspaceInput,
        *, options: RequestOptions | None = None,
    ) -> Workspace:
        """Create a new workspace."""
        data = self._do(
            "POST", "/v1/workspaces", body=workspace._to_dict(), options=options,
        )
        return Workspace._from_dict(data)

    def get_workspace(
        self, workspace_id: str, *, options: RequestOptions | None = None,
    ) -> Workspace:
        """Get a workspace by ID."""
        data = self._do("GET", f"/v1/workspaces/{workspace_id}", options=options)
        return Workspace._from_dict(data)

    def update_workspace(
        self, workspace_id: str, workspace: UpdateWorkspaceInput,
        *, options: RequestOptions | None = None,
    ) -> Workspace:
        """Update a workspace's settings."""
        data = self._do(
            "PATCH", f"/v1/workspaces/{workspace_id}",
            body=workspace._to_dict(), options=options,
        )
        return Workspace._from_dict(data)

    def delete_workspace(
        self, workspace_id: str, *, confirm_name: str,
        options: RequestOptions | None = None,
    ) -> None:
        """Delete a workspace.

        Requires *confirm_name* to match the workspace's actual name as a
        safety guard against accidental deletion.
        """
        ws = self.get_workspace(workspace_id, options=options)
        self._confirm_name("workspace", ws.name, confirm_name)
        self._do("DELETE", f"/v1/workspaces/{workspace_id}", options=options)

    # ── Projects ─────────────────────────────────────────────────────────

    def list_projects(
        self, *, workspace_id: str | None = None,
        options: RequestOptions | None = None,
    ) -> ListProjectsResponse:
        """List all projects in the org."""
        query: dict[str, str] | None = None
        if workspace_id is not None:
            query = {"workspace_id": workspace_id}
        data = self._do("GET", "/v1/projects", query=query, options=options)
        return ListProjectsResponse._from_dict(data)

    def get_project(
        self, project_id: str, *, options: RequestOptions | None = None,
    ) -> Project:
        """Get a project by ID."""
        data = self._do("GET", f"/v1/projects/{project_id}", options=options)
        return Project._from_dict(data)

    def create_project(
        self, project: CreateProjectInput,
        *, options: RequestOptions | None = None,
    ) -> Project:
        """Create a new project."""
        data = self._do(
            "POST", "/v1/projects", body=project._to_dict(), options=options,
        )
        return Project._from_dict(data)

    def update_project(
        self, project_id: str, project: UpdateProjectInput,
        *, options: RequestOptions | None = None,
    ) -> Project:
        """Update a project's settings."""
        data = self._do(
            "PATCH", f"/v1/projects/{project_id}",
            body=project._to_dict(), options=options,
        )
        return Project._from_dict(data)

    def delete_project(
        self, project_id: str, *, confirm_name: str,
        options: RequestOptions | None = None,
    ) -> None:
        """Delete a project.

        Requires *confirm_name* to match the project's actual name as a
        safety guard against accidental deletion.
        """
        proj = self.get_project(project_id, options=options)
        self._confirm_name("project", proj.name, confirm_name)
        self._do("DELETE", f"/v1/projects/{project_id}", options=options)

    def rotate_ingest_secret(
        self, project_id: str, *, options: RequestOptions | None = None,
    ) -> IngestSecretRotation:
        """Rotate the ingest secret for a project."""
        data = self._do(
            "POST", f"/v1/projects/{project_id}/ingest_secret/rotate",
            options=options,
        )
        return IngestSecretRotation._from_dict(data)

    # ── Breakers ─────────────────────────────────────────────────────────

    def list_breakers(
        self, project_id: str, params: ListParams | None = None,
        *, options: RequestOptions | None = None,
    ) -> list[Breaker]:
        """List breakers for a project."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/breakers",
            query=_list_query(params), options=options,
        )
        return [Breaker._from_dict(b) for b in data.get("breakers", [])]

    def get_breaker(
        self, project_id: str, breaker_id: str,
        *, options: RequestOptions | None = None,
    ) -> Breaker:
        """Get a single breaker."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/breakers/{breaker_id}",
            options=options,
        )
        router_id = data.get("router_id", "")
        breaker_data = data.get("breaker", data)
        return Breaker._from_dict(breaker_data, router_id=router_id)

    def create_breaker(
        self, project_id: str, breaker: CreateBreakerInput,
        *, options: RequestOptions | None = None,
    ) -> Breaker:
        """Create a new breaker."""
        data = self._do(
            "POST", f"/v1/projects/{project_id}/breakers",
            body=breaker._to_dict(), options=options,
        )
        router_id = data.get("router_id", "")
        breaker_data = data.get("breaker", data)
        return Breaker._from_dict(breaker_data, router_id=router_id)

    def update_breaker(
        self, project_id: str, breaker_id: str, breaker: UpdateBreakerInput,
        *, options: RequestOptions | None = None,
    ) -> Breaker:
        """Update a breaker's configuration."""
        data = self._do(
            "PATCH", f"/v1/projects/{project_id}/breakers/{breaker_id}",
            body=breaker._to_dict(), options=options,
        )
        router_id = data.get("router_id", "")
        breaker_data = data.get("breaker", data)
        return Breaker._from_dict(breaker_data, router_id=router_id)

    def delete_breaker(
        self, project_id: str, breaker_id: str,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Delete a breaker."""
        self._do(
            "DELETE", f"/v1/projects/{project_id}/breakers/{breaker_id}",
            options=options,
        )

    def sync_breakers(
        self, project_id: str, spec: SyncBreakersInput,
        *, options: RequestOptions | None = None,
    ) -> list[Breaker]:
        """Replace all breakers for a project (bulk sync)."""
        data = self._do(
            "PUT", f"/v1/projects/{project_id}/breakers",
            body=spec._to_dict(), options=options,
        )
        if isinstance(data, list):
            return [Breaker._from_dict(b) for b in data]
        return [Breaker._from_dict(b) for b in data.get("breakers", [])]

    def get_breaker_state(
        self, project_id: str, breaker_id: str,
        *, options: RequestOptions | None = None,
    ) -> BreakerState:
        """Get the current state of a breaker."""
        data = self._do(
            "GET",
            f"/v1/projects/{project_id}/breakers/{breaker_id}/state",
            options=options,
        )
        return BreakerState._from_dict(data)

    def batch_get_breaker_states(
        self, project_id: str, query: BatchGetBreakerStatesInput,
        *, options: RequestOptions | None = None,
    ) -> list[BreakerState]:
        """Get states for multiple breakers."""
        data = self._do(
            "POST", f"/v1/projects/{project_id}/breakers/state:batch",
            body=query._to_dict(), options=options,
        )
        if isinstance(data, list):
            return [BreakerState._from_dict(s) for s in data]
        return [BreakerState._from_dict(s) for s in data.get("states", [])]

    def update_breaker_metadata(
        self, project_id: str, breaker_id: str, metadata: dict[str, str],
        *, options: RequestOptions | None = None,
    ) -> None:
        """Merge-patch a breaker's metadata."""
        self._do(
            "PATCH",
            f"/v1/projects/{project_id}/breakers/{breaker_id}/metadata",
            body=metadata, options=options,
        )

    # ── Routers ──────────────────────────────────────────────────────────

    def list_routers(
        self, project_id: str, params: ListParams | None = None,
        *, options: RequestOptions | None = None,
    ) -> list[Router]:
        """List routers for a project."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/routers",
            query=_list_query(params), options=options,
        )
        return [Router._from_dict(r) for r in data.get("routers", [])]

    def get_router(
        self, project_id: str, router_id: str,
        *, options: RequestOptions | None = None,
    ) -> Router:
        """Get a single router."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/routers/{router_id}",
            options=options,
        )
        return Router._from_dict(data.get("router", data))

    def create_router(
        self, project_id: str, router: CreateRouterInput,
        *, options: RequestOptions | None = None,
    ) -> Router:
        """Create a new router."""
        data = self._do(
            "POST", f"/v1/projects/{project_id}/routers",
            body=router._to_dict(), options=options,
        )
        return Router._from_dict(data.get("router", data))

    def update_router(
        self, project_id: str, router_id: str, router: UpdateRouterInput,
        *, options: RequestOptions | None = None,
    ) -> Router:
        """Update a router's configuration."""
        data = self._do(
            "PATCH", f"/v1/projects/{project_id}/routers/{router_id}",
            body=router._to_dict(), options=options,
        )
        return Router._from_dict(data.get("router", data))

    def delete_router(
        self, project_id: str, router_id: str,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Delete a router (must have no linked breakers)."""
        self._do(
            "DELETE", f"/v1/projects/{project_id}/routers/{router_id}",
            options=options,
        )

    def link_breaker(
        self, project_id: str, router_id: str, link: LinkBreakerInput,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Link one or more breakers to a router atomically."""
        self._do(
            "POST",
            f"/v1/projects/{project_id}/routers/{router_id}/breakers",
            body=link._to_dict(), options=options,
        )

    def unlink_breaker(
        self, project_id: str, router_id: str, breaker_id: str,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Remove a single breaker from a router.

        To unlink multiple breakers, call this method once per breaker ID.
        """
        self._do(
            "DELETE",
            f"/v1/projects/{project_id}/routers/{router_id}/breakers/{breaker_id}",
            options=options,
        )

    def update_router_metadata(
        self, project_id: str, router_id: str, metadata: dict[str, str],
        *, options: RequestOptions | None = None,
    ) -> None:
        """Merge-patch a router's metadata."""
        self._do(
            "PATCH",
            f"/v1/projects/{project_id}/routers/{router_id}/metadata",
            body=metadata, options=options,
        )

    # ── Notification channels ────────────────────────────────────────────

    def list_notification_channels(
        self, project_id: str, params: ListParams | None = None,
        *, options: RequestOptions | None = None,
    ) -> list[NotificationChannel]:
        """List notification channels for a project."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/notification-channels",
            query=_list_query(params), options=options,
        )
        return [
            NotificationChannel._from_dict(c) for c in data.get("items", [])
        ]

    def iter_notification_channels(
        self, project_id: str, params: ListParams | None = None,
        *, options: RequestOptions | None = None,
    ) -> Iterator[NotificationChannel]:
        """Iterate over all notification channels (auto-paginates)."""
        p = params or ListParams()
        cursor = p.cursor
        while True:
            data = self._do(
                "GET", f"/v1/projects/{project_id}/notification-channels",
                query=_list_query(ListParams(cursor=cursor, limit=p.limit)),
                options=options,
            )
            items = data.get("items", [])
            for item in items:
                yield NotificationChannel._from_dict(item)
            next_cursor = data.get("next_cursor", "")
            if not next_cursor or not items:
                break
            cursor = next_cursor

    def get_notification_channel(
        self, project_id: str, channel_id: str,
        *, options: RequestOptions | None = None,
    ) -> NotificationChannel:
        """Get a single notification channel."""
        data = self._do(
            "GET",
            f"/v1/projects/{project_id}/notification-channels/{channel_id}",
            options=options,
        )
        return NotificationChannel._from_dict(data)

    def create_notification_channel(
        self, project_id: str, channel: CreateNotificationChannelInput,
        *, options: RequestOptions | None = None,
    ) -> NotificationChannel:
        """Create a new notification channel."""
        data = self._do(
            "POST", f"/v1/projects/{project_id}/notification-channels",
            body=channel._to_dict(), options=options,
        )
        return NotificationChannel._from_dict(data)

    def update_notification_channel(
        self, project_id: str, channel_id: str,
        channel: UpdateNotificationChannelInput,
        *, options: RequestOptions | None = None,
    ) -> NotificationChannel:
        """Update a notification channel."""
        data = self._do(
            "PATCH",
            f"/v1/projects/{project_id}/notification-channels/{channel_id}",
            body=channel._to_dict(), options=options,
        )
        return NotificationChannel._from_dict(data)

    def delete_notification_channel(
        self, project_id: str, channel_id: str,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Delete a notification channel."""
        self._do(
            "DELETE",
            f"/v1/projects/{project_id}/notification-channels/{channel_id}",
            options=options,
        )

    def test_notification_channel(
        self, project_id: str, channel_id: str,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Send a test notification to a channel."""
        self._do(
            "POST",
            f"/v1/projects/{project_id}/notification-channels/{channel_id}/test",
            options=options,
        )

    # ── Events ───────────────────────────────────────────────────────────

    def list_events(
        self, project_id: str, params: ListEventsParams | None = None,
        *, options: RequestOptions | None = None,
    ) -> list[Event]:
        """List state transition events for a project."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/events",
            query=_events_query(params), options=options,
        )
        return [Event._from_dict(e) for e in data.get("events", [])]

    def iter_events(
        self, project_id: str, params: ListEventsParams | None = None,
        *, options: RequestOptions | None = None,
    ) -> Iterator[Event]:
        """Iterate over all events (auto-paginates)."""
        p = params or ListEventsParams()
        cursor = p.cursor
        while True:
            effective = ListEventsParams(
                breaker_id=p.breaker_id,
                start_time=p.start_time,
                end_time=p.end_time,
                cursor=cursor,
                limit=p.limit,
            )
            data = self._do(
                "GET", f"/v1/projects/{project_id}/events",
                query=_events_query(effective), options=options,
            )
            events = data.get("events", [])
            for event in events:
                yield Event._from_dict(event)
            next_cursor = data.get("next_cursor")
            if not next_cursor or not events:
                break
            cursor = next_cursor

    # ── Project keys ─────────────────────────────────────────────────────

    def list_project_keys(
        self, project_id: str, *, options: RequestOptions | None = None,
    ) -> list[ProjectKey]:
        """List all API keys for a project."""
        data = self._do(
            "GET", f"/v1/projects/{project_id}/keys", options=options,
        )
        return [ProjectKey._from_dict(k) for k in data.get("keys", [])]

    def create_project_key(
        self, project_id: str, key: CreateProjectKeyInput | None = None,
        *, options: RequestOptions | None = None,
    ) -> CreateProjectKeyResponse:
        """Create a new project API key.

        The returned ``key`` field is only available on creation — store it
        securely.
        """
        body = key._to_dict() if key else {}
        data = self._do(
            "POST", f"/v1/projects/{project_id}/keys",
            body=body, options=options,
        )
        return CreateProjectKeyResponse._from_dict(data)

    def delete_project_key(
        self, project_id: str, key_id: str,
        *, options: RequestOptions | None = None,
    ) -> None:
        """Revoke a project API key."""
        self._do(
            "DELETE", f"/v1/projects/{project_id}/keys/{key_id}",
            options=options,
        )

    # ── Internal ─────────────────────────────────────────────────────────

    @staticmethod
    def _confirm_name(kind: str, actual: str, expected: str) -> None:
        """Raise if *actual* does not match *expected*."""
        if actual != expected:
            raise ValueError(
                f"{kind} name {actual!r} does not match "
                f"confirmation {expected!r}"
            )

    # ── Internal: HTTP ───────────────────────────────────────────────────

    def _do(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: dict[str, str] | None = None,
        options: RequestOptions | None = None,
    ) -> Any:
        """Execute an API request and return the parsed JSON response."""
        url = self._base_url + path
        opts = options or RequestOptions()

        req_headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            req_headers["Authorization"] = f"Bearer {self._api_key}"
        if body is not None:
            req_headers["Content-Type"] = "application/json"
        if opts.idempotency_key:
            req_headers["Idempotency-Key"] = opts.idempotency_key
        if opts.request_id:
            req_headers["X-Request-ID"] = opts.request_id
        if opts.headers:
            req_headers.update(opts.headers)

        content: bytes | None = None
        if body is not None:
            content = json.dumps(body, default=str).encode()

        try:
            resp = self._http.request(
                method, url, content=content, headers=req_headers,
                params=query, timeout=opts.timeout,
            )
        except httpx.HTTPError as exc:
            raise TransportError(str(exc)) from exc

        if resp.status_code >= 400:
            self._raise_for_status(resp)

        if resp.status_code == 204 or not resp.content:
            return {}

        return resp.json()

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Parse an error response and raise the appropriate exception."""
        status = resp.status_code
        request_id = resp.headers.get("x-request-id", "")

        code = ""
        message = ""
        try:
            data = resp.json()
            code = data.get("code", "")
            message = data.get("message", "")
        except Exception:
            pass

        if not message:
            message = resp.reason_phrase or f"HTTP {status}"

        retry_after: float | None = None
        if status == 429:
            raw = resp.headers.get("retry-after", "")
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    pass

        kwargs: dict[str, Any] = dict(
            status=status,
            code=code,
            request_id=request_id,
            body=resp.content,
            retry_after=retry_after,
        )

        error_cls: type[APIError]
        if status == 404:
            error_cls = NotFoundError
        elif status == 401:
            error_cls = UnauthorizedError
        elif status == 403:
            error_cls = ForbiddenError
        elif status == 429:
            error_cls = RateLimitedError
        elif status == 409:
            error_cls = ConflictError
        elif status in (400, 422):
            error_cls = ValidationError
        elif 500 <= status < 600:
            error_cls = ServerFaultError
        else:
            error_cls = APIError

        raise error_cls(message, **kwargs)


# ── Helpers ──────────────────────────────────────────────────────────────


def _list_query(params: ListParams | None) -> dict[str, str] | None:
    if params is None:
        return None
    q: dict[str, str] = {}
    if params.cursor:
        q["cursor"] = params.cursor
    if params.limit > 0:
        q["limit"] = str(params.limit)
    return q or None


def _events_query(params: ListEventsParams | None) -> dict[str, str] | None:
    if params is None:
        return None
    q: dict[str, str] = {}
    if params.breaker_id:
        q["breaker_id"] = params.breaker_id
    if params.start_time:
        q["start_time"] = params.start_time.isoformat()
    if params.end_time:
        q["end_time"] = params.end_time.isoformat()
    if params.cursor:
        q["cursor"] = params.cursor
    if params.limit > 0:
        q["limit"] = str(params.limit)
    return q or None
