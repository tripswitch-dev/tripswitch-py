"""Integration tests for the Tripswitch admin client.

Gated by environment variables — skipped unless configured.

Run with::

    TRIPSWITCH_API_KEY=eb_admin_...
    TRIPSWITCH_PROJECT_ID=proj_...
    pytest tests/test_admin_integration.py -v

Optional::

    TRIPSWITCH_BASE_URL=https://api.tripswitch.dev  (default)
"""

from __future__ import annotations

import os
import time

import pytest

from tripswitch.admin import (
    AdminClient,
    BreakerKind,
    BreakerOp,
    CreateBreakerInput,
    CreateProjectInput,
    ListEventsParams,
    ListParams,
    UpdateBreakerInput,
)
from tripswitch.errors import NotFoundError


# ── Config ──────────────────────────────────────────────────────────────


def _load_config() -> dict[str, str]:
    return {
        "api_key": os.environ.get("TRIPSWITCH_API_KEY", ""),
        "project_id": os.environ.get("TRIPSWITCH_PROJECT_ID", ""),
        "workspace_id": os.environ.get("TRIPSWITCH_WORKSPACE_ID", ""),
        "base_url": os.environ.get("TRIPSWITCH_BASE_URL", "https://api.tripswitch.dev"),
    }


def _skip_if_no_env(cfg: dict[str, str]) -> None:
    if not cfg["api_key"] or not cfg["project_id"]:
        pytest.skip("TRIPSWITCH_API_KEY and TRIPSWITCH_PROJECT_ID must be set")


def _make_client(cfg: dict[str, str]) -> AdminClient:
    return AdminClient(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
    )


# ── Projects ────────────────────────────────────────────────────────────


def test_integration_get_project():
    cfg = _load_config()
    _skip_if_no_env(cfg)

    with _make_client(cfg) as client:
        project = client.get_project(cfg["project_id"])
        assert project.id == cfg["project_id"]


def test_integration_project_crud():
    cfg = _load_config()
    _skip_if_no_env(cfg)
    if not cfg["workspace_id"]:
        pytest.skip("TRIPSWITCH_WORKSPACE_ID must be set")

    project_name = f"integration-test-project-{time.time_ns()}"

    with _make_client(cfg) as client:
        # Create
        project = client.create_project(
            CreateProjectInput(name=project_name, workspace_id=cfg["workspace_id"]),
        )
        assert project.name == project_name

        try:
            # List — verify it shows up
            result = client.list_projects()
            assert any(p.id == project.id for p in result.projects)

            # Delete
            client.delete_project(project.id, confirm_name=project_name)

            # Verify deletion
            with pytest.raises(NotFoundError):
                client.get_project(project.id)
        except Exception:
            # Best-effort cleanup
            try:
                client.delete_project(project.id, confirm_name=project_name)
            except Exception:
                pass
            raise


# ── Breakers ────────────────────────────────────────────────────────────


def test_integration_list_breakers():
    cfg = _load_config()
    _skip_if_no_env(cfg)

    with _make_client(cfg) as client:
        breakers = client.list_breakers(cfg["project_id"], ListParams(limit=10))
        assert isinstance(breakers, list)


def test_integration_breaker_crud():
    cfg = _load_config()
    _skip_if_no_env(cfg)

    breaker_name = f"integration-test-breaker-{time.time_ns()}"

    with _make_client(cfg) as client:
        # Create
        breaker = client.create_breaker(
            cfg["project_id"],
            CreateBreakerInput(
                name=breaker_name,
                metric="test_metric",
                kind=BreakerKind.ERROR_RATE,
                op=BreakerOp.GT,
                threshold=0.5,
                window_ms=60_000,
                min_count=10,
            ),
        )
        assert breaker.name == breaker_name

        try:
            # Read
            fetched = client.get_breaker(cfg["project_id"], breaker.id)
            assert fetched.name == breaker_name

            # Update
            updated = client.update_breaker(
                cfg["project_id"],
                breaker.id,
                UpdateBreakerInput(threshold=0.75),
            )
            assert updated.threshold == 0.75

            # Delete
            client.delete_breaker(cfg["project_id"], breaker.id)

            # Verify deletion
            with pytest.raises(NotFoundError):
                client.get_breaker(cfg["project_id"], breaker.id)
        except Exception:
            # Best-effort cleanup
            try:
                client.delete_breaker(cfg["project_id"], breaker.id)
            except Exception:
                pass
            raise


# ── Routers ─────────────────────────────────────────────────────────────


def test_integration_list_routers():
    cfg = _load_config()
    _skip_if_no_env(cfg)

    with _make_client(cfg) as client:
        routers = client.list_routers(cfg["project_id"], ListParams(limit=10))
        assert isinstance(routers, list)


# ── Notification channels ───────────────────────────────────────────────


def test_integration_list_notification_channels():
    cfg = _load_config()
    _skip_if_no_env(cfg)

    with _make_client(cfg) as client:
        channels = client.list_notification_channels(
            cfg["project_id"], ListParams(limit=10),
        )
        assert isinstance(channels, list)


# ── Events ──────────────────────────────────────────────────────────────


def test_integration_list_events():
    cfg = _load_config()
    _skip_if_no_env(cfg)

    with _make_client(cfg) as client:
        events = client.list_events(
            cfg["project_id"], ListEventsParams(limit=10),
        )
        assert isinstance(events, list)
