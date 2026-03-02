"""Integration tests for the Tripswitch runtime client.

Gated by environment variables — skipped unless configured.

Run with::

    TRIPSWITCH_API_KEY=eb_pk_...
    TRIPSWITCH_INGEST_SECRET=<64-char-hex>
    TRIPSWITCH_PROJECT_ID=proj_...
    TRIPSWITCH_BREAKER_NAME=my-breaker
    TRIPSWITCH_BREAKER_ROUTER_ID=router-id
    TRIPSWITCH_BREAKER_METRIC=metric-name
    pytest tests/test_integration.py -v

Optional::

    TRIPSWITCH_BASE_URL=https://api.tripswitch.dev  (default)
"""

from __future__ import annotations

import os
import time

import pytest

import tripswitch
from tripswitch import BreakerOpenError, Client, Latency


# ── Config ──────────────────────────────────────────────────────────────


def _load_config() -> dict[str, str]:
    return {
        "api_key": os.environ.get("TRIPSWITCH_API_KEY", ""),
        "ingest_secret": os.environ.get("TRIPSWITCH_INGEST_SECRET", ""),
        "project_id": os.environ.get("TRIPSWITCH_PROJECT_ID", ""),
        "base_url": os.environ.get("TRIPSWITCH_BASE_URL", "https://api.tripswitch.dev"),
        "breaker_name": os.environ.get("TRIPSWITCH_BREAKER_NAME", ""),
        "router_id": os.environ.get("TRIPSWITCH_BREAKER_ROUTER_ID", ""),
        "metric_name": os.environ.get("TRIPSWITCH_BREAKER_METRIC", ""),
    }


def _require_base(cfg: dict[str, str]) -> None:
    if not cfg["api_key"] or not cfg["project_id"]:
        pytest.skip("TRIPSWITCH_API_KEY and TRIPSWITCH_PROJECT_ID must be set")


def _require_full(cfg: dict[str, str]) -> None:
    _require_base(cfg)
    if not cfg["breaker_name"] or not cfg["router_id"] or not cfg["metric_name"]:
        pytest.skip(
            "TRIPSWITCH_BREAKER_NAME, TRIPSWITCH_BREAKER_ROUTER_ID, "
            "and TRIPSWITCH_BREAKER_METRIC must be set"
        )


def _make_client(cfg: dict[str, str], **overrides) -> Client:
    return Client(
        cfg["project_id"],
        api_key=cfg["api_key"],
        ingest_secret=cfg.get("ingest_secret", ""),
        base_url=cfg["base_url"],
        **overrides,
    )


# ── Tests ───────────────────────────────────────────────────────────────


def test_integration_connect():
    cfg = _load_config()
    _require_full(cfg)

    with _make_client(cfg, timeout=10) as client:
        assert client.stats.sse_connected


def test_integration_execute():
    cfg = _load_config()
    _require_full(cfg)

    with _make_client(cfg, timeout=10) as client:
        try:
            result = client.execute(
                lambda: "success",
                breakers=[cfg["breaker_name"]],
                router=cfg["router_id"],
                metrics={cfg["metric_name"]: Latency},
            )
            assert result == "success"
        except BreakerOpenError:
            pass  # expected if breaker is tripped


def test_integration_stats():
    cfg = _load_config()
    _require_full(cfg)

    with _make_client(cfg, timeout=10) as client:
        stats = client.stats
        assert stats.sse_connected


def test_integration_graceful_shutdown():
    cfg = _load_config()
    _require_full(cfg)

    client = _make_client(cfg, timeout=10)
    client.connect()

    for _ in range(5):
        try:
            client.execute(
                lambda: 42,
                breakers=[cfg["breaker_name"]],
                router=cfg["router_id"],
                metrics={cfg["metric_name"]: Latency},
            )
        except BreakerOpenError:
            pass

    client.close(timeout=5)


def test_integration_get_status():
    cfg = _load_config()
    _require_full(cfg)

    with _make_client(cfg, timeout=10) as client:
        status = client.get_status()
        assert status.open_count >= 0
        assert status.closed_count >= 0


def test_integration_metadata_sync():
    cfg = _load_config()
    _require_base(cfg)

    with _make_client(cfg, timeout=10, metadata_sync_interval=5) as client:
        # Give metadata sync time to complete initial fetch
        time.sleep(0.5)

        breakers = client.get_breakers_metadata()
        routers = client.get_routers_metadata()

        if breakers is not None:
            for b in breakers:
                assert b.id
                assert b.name

        if routers is not None:
            for r in routers:
                assert r.id
                assert r.name
