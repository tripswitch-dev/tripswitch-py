"""Tests for the admin client — types, serialization, error handling, API calls."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from tripswitch.admin import (
    AdminClient,
    Breaker,
    BreakerKind,
    BreakerOp,
    BreakerState,
    CreateBreakerInput,
    CreateNotificationChannelInput,
    CreateProjectInput,
    CreateProjectKeyInput,
    CreateRouterInput,
    Event,
    HalfOpenPolicy,
    LinkBreakerInput,
    ListEventsParams,
    ListParams,
    NotificationChannel,
    NotificationChannelType,
    NotificationEventType,
    Project,
    Router,
    RouterMode,
    SyncBreakersInput,
    UpdateBreakerInput,
    UpdateProjectInput,
    UpdateRouterInput,
)
from tripswitch.errors import (
    NotFoundError,
    RateLimitedError,
    ServerFaultError,
    TransportError,
    UnauthorizedError,
    ValidationError,
)


# ── Type serialization ───────────────────────────────────────────────────


class TestCreateBreakerInput:
    def test_required_fields_only(self):
        inp = CreateBreakerInput(
            name="test", metric="latency", kind=BreakerKind.P95,
            op=BreakerOp.GT, threshold=500,
        )
        d = inp._to_dict()
        assert d == {
            "name": "test",
            "metric": "latency",
            "kind": "p95",
            "op": "gt",
            "threshold": 500,
        }

    def test_optional_fields_included(self):
        inp = CreateBreakerInput(
            name="test", metric="m", kind=BreakerKind.ERROR_RATE,
            op=BreakerOp.GTE, threshold=0.05,
            window_ms=60000, min_count=10,
            metadata={"env": "prod"},
        )
        d = inp._to_dict()
        assert d["window_ms"] == 60000
        assert d["min_count"] == 10
        assert d["metadata"] == {"env": "prod"}
        assert "cooldown_ms" not in d  # None → omitted

    def test_enum_serializes_to_string(self):
        inp = CreateBreakerInput(
            name="b", metric="m", kind=BreakerKind.CONSECUTIVE_FAILURES,
            op=BreakerOp.LTE, threshold=3,
            half_open_indeterminate_policy=HalfOpenPolicy.PESSIMISTIC,
        )
        d = inp._to_dict()
        assert d["kind"] == "consecutive_failures"
        assert d["half_open_indeterminate_policy"] == "pessimistic"


class TestUpdateBreakerInput:
    def test_empty_update(self):
        assert UpdateBreakerInput()._to_dict() == {}

    def test_partial_update(self):
        inp = UpdateBreakerInput(name="new-name", threshold=100.0)
        d = inp._to_dict()
        assert d == {"name": "new-name", "threshold": 100.0}
        assert "metric" not in d


class TestUpdateProjectInput:
    def test_partial_update(self):
        inp = UpdateProjectInput(name="renamed")
        assert inp._to_dict() == {"name": "renamed"}


class TestBreakerDeserialization:
    def test_from_dict(self):
        d = {
            "id": "brk_123",
            "name": "api-latency",
            "metric": "latency_ms",
            "kind": "p95",
            "op": "gt",
            "threshold": 500.0,
            "window_ms": 60000,
            "metadata": {"tier": "critical"},
        }
        b = Breaker._from_dict(d)
        assert b.id == "brk_123"
        assert b.kind == BreakerKind.P95
        assert b.op == BreakerOp.GT
        assert b.threshold == 500.0
        assert b.metadata == {"tier": "critical"}

    def test_from_dict_with_router_id(self):
        b = Breaker._from_dict({"id": "b", "name": "b", "metric": "m",
                                 "kind": "avg", "op": "lt", "threshold": 1},
                                router_id="rtr_99")
        assert b.router_id == "rtr_99"


class TestRouterDeserialization:
    def test_from_dict(self):
        d = {
            "id": "rtr_1",
            "name": "main-router",
            "mode": "canary",
            "enabled": True,
            "breaker_count": 2,
            "breakers": [
                {"id": "b1", "name": "b1", "metric": "m",
                 "kind": "error_rate", "op": "gt", "threshold": 0.5},
            ],
        }
        r = Router._from_dict(d)
        assert r.mode == RouterMode.CANARY
        assert r.breaker_count == 2
        assert len(r.breakers) == 1


class TestProjectDeserialization:
    def test_from_dict_with_project_id_key(self):
        d = {"project_id": "proj_abc", "name": "My Project"}
        p = Project._from_dict(d)
        assert p.id == "proj_abc"

    def test_from_dict_with_id_key(self):
        d = {"id": "proj_xyz", "name": "Other"}
        p = Project._from_dict(d)
        assert p.id == "proj_xyz"


class TestNotificationChannelInput:
    def test_create_serialization(self):
        inp = CreateNotificationChannelInput(
            name="slack-alerts",
            channel=NotificationChannelType.SLACK,
            config={"webhook_url": "https://hooks.slack.com/..."},
            events=[NotificationEventType.TRIP, NotificationEventType.RECOVER],
        )
        d = inp._to_dict()
        assert d["channel"] == "slack"
        assert d["events"] == ["trip", "recover"]


class TestSyncBreakersInput:
    def test_serialization(self):
        inp = SyncBreakersInput(breakers=[
            CreateBreakerInput(
                name="b1", metric="m", kind=BreakerKind.AVG,
                op=BreakerOp.GT, threshold=100,
            ),
        ])
        d = inp._to_dict()
        assert len(d["breakers"]) == 1
        assert d["breakers"][0]["name"] == "b1"


# ── Admin client API calls ───────────────────────────────────────────────


BASE = "https://api.tripswitch.dev"


class TestAdminClientErrors:
    @respx.mock
    def test_404_raises_not_found(self):
        respx.get(f"{BASE}/v1/projects/proj_1").mock(
            return_value=httpx.Response(
                404, json={"code": "not_found", "message": "project not found"}
            )
        )
        client = AdminClient(api_key="eb_admin_test")
        with pytest.raises(NotFoundError) as exc_info:
            client.get_project("proj_1")
        assert exc_info.value.status == 404
        assert exc_info.value.code == "not_found"

    @respx.mock
    def test_401_raises_unauthorized(self):
        respx.get(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(401, json={"message": "bad key"})
        )
        client = AdminClient(api_key="bad")
        with pytest.raises(UnauthorizedError):
            client.list_projects()

    @respx.mock
    def test_429_raises_rate_limited_with_retry_after(self):
        respx.get(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(
                429, json={"message": "slow down"},
                headers={"Retry-After": "30"},
            )
        )
        client = AdminClient(api_key="k")
        with pytest.raises(RateLimitedError) as exc_info:
            client.list_projects()
        assert exc_info.value.retry_after == 30.0

    @respx.mock
    def test_422_raises_validation(self):
        respx.post(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(
                422, json={"code": "invalid", "message": "name required"}
            )
        )
        client = AdminClient(api_key="k")
        with pytest.raises(ValidationError):
            client.create_project(CreateProjectInput(name=""))

    @respx.mock
    def test_500_raises_server_fault(self):
        respx.get(f"{BASE}/v1/projects/p1").mock(
            return_value=httpx.Response(500, json={"message": "internal"})
        )
        client = AdminClient(api_key="k")
        with pytest.raises(ServerFaultError):
            client.get_project("p1")


class TestAdminClientProjects:
    @respx.mock
    def test_list_projects(self):
        respx.get(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(200, json={
                "projects": [
                    {"project_id": "p1", "name": "Alpha"},
                    {"project_id": "p2", "name": "Beta"},
                ]
            })
        )
        client = AdminClient(api_key="k")
        projects = client.list_projects()
        assert len(projects) == 2
        assert projects[0].id == "p1"
        assert projects[1].name == "Beta"

    @respx.mock
    def test_get_project(self):
        respx.get(f"{BASE}/v1/projects/p1").mock(
            return_value=httpx.Response(200, json={
                "project_id": "p1", "name": "Alpha",
                "enable_signed_ingest": True,
            })
        )
        client = AdminClient(api_key="k")
        p = client.get_project("p1")
        assert p.id == "p1"
        assert p.enable_signed_ingest is True

    @respx.mock
    def test_create_project(self):
        respx.post(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(200, json={
                "project_id": "p_new", "name": "New"
            })
        )
        client = AdminClient(api_key="k")
        p = client.create_project(CreateProjectInput(name="New"))
        assert p.name == "New"

    @respx.mock
    def test_delete_project_requires_confirmation(self):
        respx.get(f"{BASE}/v1/projects/p1").mock(
            return_value=httpx.Response(200, json={
                "project_id": "p1", "name": "Prod"
            })
        )
        client = AdminClient(api_key="k")
        with pytest.raises(ValueError, match="does not match"):
            client.delete_project("p1", confirm_name="wrong-name")

    @respx.mock
    def test_delete_project_success(self):
        respx.get(f"{BASE}/v1/projects/p1").mock(
            return_value=httpx.Response(200, json={
                "project_id": "p1", "name": "Prod"
            })
        )
        respx.delete(f"{BASE}/v1/projects/p1").mock(
            return_value=httpx.Response(204)
        )
        client = AdminClient(api_key="k")
        client.delete_project("p1", confirm_name="Prod")  # should not raise


class TestAdminClientBreakers:
    @respx.mock
    def test_list_breakers(self):
        respx.get(f"{BASE}/v1/projects/p1/breakers").mock(
            return_value=httpx.Response(200, json={
                "breakers": [
                    {"id": "b1", "name": "latency", "metric": "lat",
                     "kind": "p95", "op": "gt", "threshold": 500},
                ],
                "count": 1,
            })
        )
        client = AdminClient(api_key="k")
        breakers = client.list_breakers("p1")
        assert len(breakers) == 1
        assert breakers[0].kind == BreakerKind.P95

    @respx.mock
    def test_create_breaker(self):
        respx.post(f"{BASE}/v1/projects/p1/breakers").mock(
            return_value=httpx.Response(200, json={
                "breaker": {
                    "id": "b_new", "name": "err", "metric": "error_rate",
                    "kind": "error_rate", "op": "gte", "threshold": 0.05,
                },
                "router_id": "rtr_auto",
            })
        )
        client = AdminClient(api_key="k")
        b = client.create_breaker("p1", CreateBreakerInput(
            name="err", metric="error_rate",
            kind=BreakerKind.ERROR_RATE, op=BreakerOp.GTE, threshold=0.05,
        ))
        assert b.id == "b_new"
        assert b.router_id == "rtr_auto"

    @respx.mock
    def test_get_breaker_state(self):
        respx.get(f"{BASE}/v1/projects/p1/breakers/b1/state").mock(
            return_value=httpx.Response(200, json={
                "breaker_id": "b1", "state": "half_open",
                "allow_rate": 0.3, "updated_at": "2024-01-15T10:30:00Z",
            })
        )
        client = AdminClient(api_key="k")
        s = client.get_breaker_state("p1", "b1")
        assert s.state == "half_open"
        assert s.allow_rate == 0.3


class TestAdminClientRouters:
    @respx.mock
    def test_create_router(self):
        respx.post(f"{BASE}/v1/projects/p1/routers").mock(
            return_value=httpx.Response(200, json={
                "id": "rtr_1", "name": "main", "mode": "static",
                "enabled": True,
            })
        )
        client = AdminClient(api_key="k")
        r = client.create_router("p1", CreateRouterInput(
            name="main", mode=RouterMode.STATIC,
        ))
        assert r.id == "rtr_1"
        assert r.mode == RouterMode.STATIC

    @respx.mock
    def test_link_breaker(self):
        route = respx.post(f"{BASE}/v1/projects/p1/routers/rtr_1/breakers").mock(
            return_value=httpx.Response(204)
        )
        client = AdminClient(api_key="k")
        client.link_breaker("p1", "rtr_1", LinkBreakerInput(breaker_id="b1"))
        assert route.called

    @respx.mock
    def test_unlink_breaker(self):
        route = respx.delete(
            f"{BASE}/v1/projects/p1/routers/rtr_1/breakers/b1"
        ).mock(return_value=httpx.Response(204))
        client = AdminClient(api_key="k")
        client.unlink_breaker("p1", "rtr_1", "b1")
        assert route.called


class TestAdminClientNotifications:
    @respx.mock
    def test_create_notification_channel(self):
        respx.post(f"{BASE}/v1/projects/p1/notification-channels").mock(
            return_value=httpx.Response(200, json={
                "id": "nc_1", "project_id": "p1", "name": "slack",
                "channel": "slack", "config": {}, "events": ["trip"],
                "enabled": True,
            })
        )
        client = AdminClient(api_key="k")
        nc = client.create_notification_channel("p1",
            CreateNotificationChannelInput(
                name="slack",
                channel=NotificationChannelType.SLACK,
                config={"url": "https://..."},
                events=[NotificationEventType.TRIP],
            ),
        )
        assert nc.channel == NotificationChannelType.SLACK

    @respx.mock
    def test_test_notification_channel(self):
        route = respx.post(
            f"{BASE}/v1/projects/p1/notification-channels/nc_1/test"
        ).mock(return_value=httpx.Response(204))
        client = AdminClient(api_key="k")
        client.test_notification_channel("p1", "nc_1")
        assert route.called


class TestAdminClientEvents:
    @respx.mock
    def test_list_events(self):
        respx.get(f"{BASE}/v1/projects/p1/events").mock(
            return_value=httpx.Response(200, json={
                "events": [
                    {"id": "e1", "project_id": "p1", "breaker_id": "b1",
                     "from_state": "closed", "to_state": "open",
                     "timestamp": "2024-01-15T10:00:00Z"},
                ],
                "returned": 1,
            })
        )
        client = AdminClient(api_key="k")
        events = client.list_events("p1")
        assert len(events) == 1
        assert events[0].to_state == "open"


class TestAdminClientKeys:
    @respx.mock
    def test_create_project_key(self):
        respx.post(f"{BASE}/v1/projects/p1/keys").mock(
            return_value=httpx.Response(200, json={
                "id": "key_1", "name": "ci-key",
                "key": "eb_pk_secret123", "key_prefix": "eb_pk_sec",
            })
        )
        client = AdminClient(api_key="k")
        resp = client.create_project_key("p1", CreateProjectKeyInput(name="ci-key"))
        assert resp.key == "eb_pk_secret123"

    @respx.mock
    def test_delete_project_key(self):
        route = respx.delete(f"{BASE}/v1/projects/p1/keys/key_1").mock(
            return_value=httpx.Response(204)
        )
        client = AdminClient(api_key="k")
        client.delete_project_key("p1", "key_1")
        assert route.called
