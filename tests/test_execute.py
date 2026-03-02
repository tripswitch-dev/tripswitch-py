"""Tests for Client.execute() — breaker gating, metrics, error handling."""

from __future__ import annotations

import pytest

import tripswitch
from tripswitch import BreakerOpenError, ConflictingOptionsError, MetadataUnavailableError, Latency
from tripswitch.client import _Sample
from tests.conftest import make_client, set_breaker_state


class TestBreakerGating:
    def test_closed_breaker_allows_execution(self):
        c = make_client()
        set_breaker_state(c, "my-breaker", "closed")

        result = c.execute(lambda: 42, breakers=["my-breaker"])
        assert result == 42

    def test_open_breaker_raises(self):
        c = make_client()
        set_breaker_state(c, "my-breaker", "open")

        with pytest.raises(BreakerOpenError) as exc_info:
            c.execute(lambda: 42, breakers=["my-breaker"])
        assert exc_info.value.breaker == "my-breaker"

    def test_unknown_breaker_allows_execution(self):
        """Breakers not in cache are assumed closed (fail-open)."""
        c = make_client()
        result = c.execute(lambda: "ok", breakers=["nonexistent"])
        assert result == "ok"

    def test_half_open_with_zero_allow_rate_always_rejects(self):
        c = make_client()
        set_breaker_state(c, "b", "half_open", allow_rate=0.0)

        with pytest.raises(BreakerOpenError):
            c.execute(lambda: 42, breakers=["b"])

    def test_half_open_with_full_allow_rate_always_allows(self):
        c = make_client()
        set_breaker_state(c, "b", "half_open", allow_rate=1.0)

        result = c.execute(lambda: 42, breakers=["b"])
        assert result == 42

    def test_multiple_breakers_open_any_rejects(self):
        c = make_client()
        set_breaker_state(c, "a", "closed")
        set_breaker_state(c, "b", "open")

        with pytest.raises(BreakerOpenError) as exc_info:
            c.execute(lambda: 42, breakers=["a", "b"])
        assert exc_info.value.breaker == "b"

    def test_no_breakers_skips_gating(self):
        c = make_client()
        result = c.execute(lambda: "no-gate")
        assert result == "no-gate"


class TestConflictingOptions:
    def test_breakers_and_select_breakers_conflicts(self):
        c = make_client()
        with pytest.raises(ConflictingOptionsError):
            c.execute(
                lambda: 42,
                breakers=["x"],
                select_breakers=lambda metas: ["x"],
            )

    def test_router_and_select_router_conflicts(self):
        c = make_client()
        with pytest.raises(ConflictingOptionsError):
            c.execute(lambda: 42, router="r", select_router=lambda metas: "r")


class TestDynamicSelection:
    def test_select_breakers_metadata_unavailable(self):
        c = make_client()
        # metadata cache is None by default
        with pytest.raises(MetadataUnavailableError):
            c.execute(lambda: 42, select_breakers=lambda m: [])

    def test_select_router_metadata_unavailable(self):
        c = make_client()
        with pytest.raises(MetadataUnavailableError):
            c.execute(lambda: 42, select_router=lambda m: "")


class TestErrorHandling:
    def test_task_error_propagates(self):
        c = make_client()

        with pytest.raises(ValueError, match="boom"):
            c.execute(lambda: (_ for _ in ()).throw(ValueError("boom")))

    def test_task_exception_propagated(self):
        c = make_client()

        def bad_task():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError, match="fail"):
            c.execute(bad_task)

    def test_ignore_errors(self):
        c = make_client()
        collected: list[_Sample] = []
        orig_enqueue = c._enqueue
        c._enqueue = lambda s: collected.append(s)

        def task():
            raise TimeoutError("slow")

        with pytest.raises(TimeoutError):
            c.execute(
                task,
                router="r",
                metrics={"latency": Latency},
                ignore_errors=[TimeoutError],
            )

        # Should be marked OK because TimeoutError is ignored
        assert all(s.ok for s in collected)

    def test_error_evaluator_takes_precedence(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        def task():
            raise ValueError("not a real failure")

        with pytest.raises(ValueError):
            c.execute(
                task,
                router="r",
                metrics={"m": 1.0},
                error_evaluator=lambda e: False,  # Nothing is a failure
            )

        assert all(s.ok for s in collected)


class TestMetrics:
    def test_latency_sentinel(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(lambda: 42, router="r", metrics={"latency": Latency})

        assert len(collected) == 1
        assert collected[0].metric == "latency"
        assert collected[0].value >= 0  # some positive duration

    def test_static_numeric_metric(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(lambda: None, router="r", metrics={"count": 5})

        assert len(collected) == 1
        assert collected[0].metric == "count"
        assert collected[0].value == 5.0

    def test_callable_metric(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        counter = [0]

        def metric_fn():
            counter[0] += 1
            return float(counter[0])

        c.execute(lambda: None, router="r", metrics={"calls": metric_fn})

        assert collected[0].value == 1.0

    def test_deferred_metrics(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(
            lambda: {"tokens": 150},
            router="r",
            deferred_metrics=lambda res, err: {"token_count": float(res["tokens"])},
        )

        metrics_by_name = {s.metric: s for s in collected}
        assert "token_count" in metrics_by_name
        assert metrics_by_name["token_count"].value == 150.0

    def test_no_router_no_samples(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(lambda: 42, metrics={"latency": Latency})

        assert len(collected) == 0

    def test_empty_metric_key_ignored(self):
        c = make_client()
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(lambda: None, router="r", metrics={"": 1.0, "valid": 2.0})

        assert len(collected) == 1
        assert collected[0].metric == "valid"


class TestTags:
    def test_global_tags_applied(self):
        c = make_client(global_tags={"env": "test"})
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(lambda: None, router="r", metrics={"m": 1.0})

        assert collected[0].tags == {"env": "test"}

    def test_call_tags_override_global(self):
        c = make_client(global_tags={"env": "prod", "region": "us"})
        collected: list[_Sample] = []
        c._enqueue = lambda s: collected.append(s)

        c.execute(
            lambda: None,
            router="r",
            metrics={"m": 1.0},
            tags={"env": "staging"},
        )

        assert collected[0].tags == {"env": "staging", "region": "us"}
