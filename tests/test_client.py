"""Tests for Client state queries, report, and stats."""

from __future__ import annotations

import pytest

from tripswitch import BreakerMeta, BreakerStatus, RouterMeta
from tripswitch.client import _Sample
from tests.conftest import make_client, set_breaker_state


class TestStateQueries:
    def test_get_state_returns_none_for_unknown(self):
        c = make_client()
        assert c.get_state("nope") is None

    def test_get_state_returns_status(self):
        c = make_client()
        set_breaker_state(c, "b", "half_open", 0.5)

        status = c.get_state("b")
        assert status is not None
        assert status == BreakerStatus(name="b", state="half_open", allow_rate=0.5)

    def test_get_all_states(self):
        c = make_client()
        set_breaker_state(c, "a", "closed")
        set_breaker_state(c, "b", "open")

        states = c.get_all_states()
        assert len(states) == 2
        assert states["a"].state == "closed"
        assert states["b"].state == "open"

    def test_get_all_states_empty(self):
        c = make_client()
        assert c.get_all_states() == {}


class TestMetadataCache:
    def test_breakers_metadata_none_when_empty(self):
        c = make_client()
        assert c.get_breakers_metadata() is None

    def test_breakers_metadata_returns_copy(self):
        c = make_client()
        with c._meta_lock:
            c._breakers_meta = [
                BreakerMeta(id="b1", name="breaker-1", metadata={"tier": "critical"})
            ]

        meta = c.get_breakers_metadata()
        assert meta is not None
        assert len(meta) == 1
        assert meta[0].name == "breaker-1"
        assert meta[0].metadata["tier"] == "critical"

        # Verify metadata is immutable
        with pytest.raises(TypeError):
            meta[0].metadata["tier"] = "low"

        # Verify it's a separate object from the cache
        assert meta[0] is not c._breakers_meta[0]

    def test_routers_metadata_none_when_empty(self):
        c = make_client()
        assert c.get_routers_metadata() is None

    def test_routers_metadata_returns_copy(self):
        c = make_client()
        with c._meta_lock:
            c._routers_meta = [
                RouterMeta(id="r1", name="router-1", metadata={"env": "prod"})
            ]

        meta = c.get_routers_metadata()
        assert meta is not None
        assert meta[0].metadata["env"] == "prod"


class TestReport:
    def test_report_enqueues_sample(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.report(router_id="r", metric="m", value=3.14, ok=True)

        assert len(collected) == 1
        assert collected[0].router_id == "r"
        assert collected[0].metric == "m"
        assert collected[0].value == 3.14
        assert collected[0].ok is True

    def test_report_missing_fields_logs_warning(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.report(router_id="", metric="m")
        c.report(router_id="r", metric="")

        assert len(collected) == 0

    def test_report_merges_tags(self):
        c = make_client(global_tags={"env": "test"})
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.report(router_id="r", metric="m", tags={"extra": "yes"})

        assert collected[0].tags == {"env": "test", "extra": "yes"}


class TestStats:
    def test_initial_stats(self):
        c = make_client()
        s = c.stats
        assert s.dropped_samples == 0
        assert s.sse_connected is False
        assert s.cached_breakers == 0

    def test_stats_reflect_state(self):
        c = make_client()
        set_breaker_state(c, "a", "closed")
        set_breaker_state(c, "b", "open")

        s = c.stats
        assert s.cached_breakers == 2


class TestSampleFormat:
    def test_to_dict_minimal(self):
        s = _Sample(router_id="r", metric="m", ts_ms=1000, value=1.0, ok=True)
        d = s.to_dict()
        assert d == {
            "router_id": "r",
            "metric": "m",
            "ts_ms": 1000,
            "value": 1.0,
            "ok": True,
        }
        assert "tags" not in d
        assert "trace_id" not in d

    def test_to_dict_with_tags_and_trace(self):
        s = _Sample(
            router_id="r", metric="m", ts_ms=1000, value=1.0, ok=False,
            tags={"k": "v"}, trace_id="trace-abc",
        )
        d = s.to_dict()
        assert d["tags"] == {"k": "v"}
        assert d["trace_id"] == "trace-abc"
