"""Tripswitch runtime client."""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar

import httpx

from tripswitch._sse import parse_sse_stream
from tripswitch.errors import (
    BreakerOpenError,
    ConflictingOptionsError,
    MetadataUnavailableError,
    UnauthorizedError,
)
from tripswitch.types import (
    BreakerMeta,
    BreakerStatus,
    Latency,
    RouterMeta,
    SDKStats,
    Status,
)

logger = logging.getLogger("tripswitch")

T = TypeVar("T")

CLIENT_VERSION = "0.1.0"
CONTRACT_VERSION = "0.2"

_DEFAULT_BASE_URL = "https://api.tripswitch.dev"
_BUFFER_SIZE = 10_000
_BATCH_SIZE = 500
_FLUSH_INTERVAL = 15.0  # seconds
_DEFAULT_META_SYNC_INTERVAL = 30.0  # seconds
_HTTP_TIMEOUT = 30.0  # seconds
_BACKOFF_SCHEDULE = (0.1, 0.4, 1.0)  # seconds
_SSE_RECONNECT_BACKOFFS = (1, 2, 4, 8, 15, 30)  # seconds, capped


# ── Internal types ───────────────────────────────────────────────────────


@dataclass
class _BreakerState:
    state: str  # "open", "closed", "half_open"
    allow_rate: float = 0.0


@dataclass
class _Sample:
    router_id: str
    metric: str
    ts_ms: int
    value: float
    ok: bool
    tags: dict[str, str] | None = None
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "router_id": self.router_id,
            "metric": self.metric,
            "ts_ms": self.ts_ms,
            "value": self.value,
            "ok": self.ok,
        }
        if self.tags:
            d["tags"] = self.tags
        if self.trace_id:
            d["trace_id"] = self.trace_id
        return d


# ── Client ───────────────────────────────────────────────────────────────


class Client:
    """Tripswitch runtime client.

    Maintains real-time circuit breaker state via SSE and reports execution
    samples to the Tripswitch ingest API.  Thread-safe.

    Use as a context manager for automatic lifecycle management::

        with tripswitch.Client(
            "proj_abc",
            api_key="eb_pk_...",
            ingest_secret="64-char-hex",
        ) as ts:
            result = ts.execute(
                my_task,
                breakers=["checkout-latency"],
                router="checkout-router",
                metrics={"latency": Latency},
            )

    Or manage manually::

        ts = tripswitch.Client(...)
        ts.connect()
        try:
            ...
        finally:
            ts.close()
    """

    def __init__(
        self,
        project_id: str,
        *,
        api_key: str = "",
        ingest_secret: str = "",
        fail_open: bool = True,
        base_url: str = _DEFAULT_BASE_URL,
        on_state_change: Callable[[str, str, str], None] | None = None,
        trace_id_extractor: Callable[[], str] | None = None,
        global_tags: dict[str, str] | None = None,
        metadata_sync_interval: float = _DEFAULT_META_SYNC_INTERVAL,
        timeout: float | None = None,
    ):
        self.project_id = project_id

        self._api_key = api_key
        self._ingest_secret = ingest_secret
        self._fail_open = fail_open
        self._base_url = base_url.rstrip("/")
        self._on_state_change = on_state_change
        self._trace_id_extractor = trace_id_extractor
        self._global_tags: dict[str, str] = dict(global_tags) if global_tags else {}
        self._meta_sync_interval = metadata_sync_interval
        self._init_timeout = timeout

        # Breaker state cache
        self._states: dict[str, _BreakerState] = {}
        self._states_lock = threading.RLock()

        # Metadata cache
        self._breakers_meta: list[BreakerMeta] | None = None
        self._routers_meta: list[RouterMeta] | None = None
        self._breakers_etag = ""
        self._routers_etag = ""
        self._meta_lock = threading.RLock()

        # Sample buffer
        self._queue: queue.Queue[_Sample | None] = queue.Queue(maxsize=_BUFFER_SIZE)
        self._dropped_samples = 0
        self._dropped_lock = threading.Lock()

        # Stats
        self._stats_lock = threading.RLock()
        self._sse_connected = False
        self._sse_reconnects = 0
        self._last_flush: datetime | None = None
        self._last_sse_event: datetime | None = None
        self._flush_failures = 0

        # Threading
        self._shutdown = threading.Event()
        self._sse_ready = threading.Event()
        self._threads: list[threading.Thread] = []
        self._send_workers: list[threading.Thread] = []
        self._connected = False

        # HTTP
        self._http = httpx.Client(timeout=_HTTP_TIMEOUT)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def connect(self, timeout: float | None = None) -> None:
        """Start background threads and wait for initial SSE sync.

        Args:
            timeout: Max seconds to wait for the first SSE event.
                     Overrides the *timeout* passed to ``__init__``.
        """
        if self._connected:
            return
        self._connected = True

        wait = timeout if timeout is not None else self._init_timeout

        # SSE listener
        self._start_thread(self._sse_listener, "tripswitch-sse")
        # Sample flusher
        self._start_thread(self._flusher, "tripswitch-flusher")
        # Metadata sync
        if self._meta_sync_interval > 0:
            self._start_thread(self._metadata_sync, "tripswitch-meta")

        # Block until first SSE event (or timeout)
        if self._api_key:
            if wait is not None:
                if not self._sse_ready.wait(timeout=wait):
                    self.close()
                    raise TimeoutError(
                        "tripswitch: timed out waiting for initial SSE sync"
                    )
            else:
                self._sse_ready.wait()

    def close(self, timeout: float = 5.0) -> None:
        """Shut down gracefully, flushing buffered samples.

        Args:
            timeout: Max seconds to wait for in-flight flushes.
        """
        if not self._connected:
            return
        self._shutdown.set()

        # Tell the flusher to drain
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        deadline = time.monotonic() + timeout
        for t in self._threads + self._send_workers:
            remaining = max(deadline - time.monotonic(), 0)
            t.join(timeout=remaining)

        self._http.close()
        self._connected = False

    def __enter__(self) -> Client:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Execute ──────────────────────────────────────────────────────────

    def execute(
        self,
        task: Callable[[], T],
        *,
        breakers: list[str] | None = None,
        select_breakers: Callable[[list[BreakerMeta]], list[str]] | None = None,
        router: str | None = None,
        select_router: Callable[[list[RouterMeta]], str] | None = None,
        metrics: dict[str, Any] | None = None,
        deferred_metrics: Callable[[Any, Exception | None], dict[str, float]] | None = None,
        tags: dict[str, str] | None = None,
        ignore_errors: list[type[Exception]] | None = None,
        error_evaluator: Callable[[Exception], bool] | None = None,
        trace_id: str | None = None,
    ) -> T:
        """Execute *task* with optional circuit-breaker gating and metric reporting.

        Args:
            task: Zero-arg callable whose return value is passed through.
            breakers: Static breaker names to check. Raises
                :class:`~tripswitch.BreakerOpenError` if any is open.
            select_breakers: Pick breakers dynamically from cached metadata.
                Mutually exclusive with *breakers*.
            router: Router ID for sample routing.  Required for metrics
                to be emitted.
            select_router: Pick a router dynamically from cached metadata.
                Mutually exclusive with *router*.
            metrics: Metric values to report.  Keys are metric names;
                values may be :data:`Latency`, a ``Callable[[], float]``,
                or a numeric literal.
            deferred_metrics: Called with ``(result, error)`` after *task*
                to extract metrics from the return value.
            tags: Per-call tags (merged with *global_tags*; call-site wins).
            ignore_errors: Exception **types** that should not count as
                failures.
            error_evaluator: Returns ``True`` if the exception is a failure.
                Takes precedence over *ignore_errors*.
            trace_id: Correlation ID.  Falls back to *trace_id_extractor*.

        Returns:
            The return value of *task()*.

        Raises:
            BreakerOpenError: A checked breaker is open or probabilistically
                throttled in half-open state.
            ConflictingOptionsError: Mutually exclusive options were combined.
            MetadataUnavailableError: A selector was used but the metadata
                cache is empty.
        """
        # ── validate
        if breakers and select_breakers:
            raise ConflictingOptionsError(
                "cannot combine 'breakers' and 'select_breakers'"
            )
        if router and select_router:
            raise ConflictingOptionsError(
                "cannot combine 'router' and 'select_router'"
            )

        # ── resolve dynamic breakers
        resolved_breakers = list(breakers) if breakers else []
        if select_breakers is not None:
            meta = self.get_breakers_metadata()
            if meta is None:
                raise MetadataUnavailableError("breaker metadata cache is empty")
            try:
                resolved_breakers = select_breakers(meta) or []
            except Exception:
                logger.warning("breaker selector raised", exc_info=True)
                resolved_breakers = []

        # ── resolve dynamic router
        resolved_router = router or ""
        if select_router is not None:
            meta = self.get_routers_metadata()
            if meta is None:
                raise MetadataUnavailableError("router metadata cache is empty")
            try:
                resolved_router = select_router(meta) or ""
            except Exception:
                logger.warning("router selector raised", exc_info=True)
                resolved_router = ""

        # ── breaker gating
        self._check_breakers(resolved_breakers)

        # ── run task
        start_mono = time.monotonic()
        start_ts_ms = int(time.time() * 1000)

        result: T | None = None
        task_error: Exception | None = None
        try:
            result = task()
        except Exception as exc:
            task_error = exc

        duration_ms = (time.monotonic() - start_mono) * 1000

        # ── determine OK
        ok = self._is_ok(task_error, ignore_errors, error_evaluator)

        # ── trace ID
        resolved_trace = trace_id or ""
        if not resolved_trace and self._trace_id_extractor:
            try:
                resolved_trace = self._trace_id_extractor()
            except Exception:
                pass

        # ── emit samples
        has_metrics = bool(metrics) or deferred_metrics is not None
        if has_metrics and not resolved_router:
            logger.warning(
                "metrics specified without a router — samples will not be emitted"
            )

        if resolved_router:
            samples = self._resolve_metrics(metrics or {}, duration_ms)

            if deferred_metrics is not None:
                try:
                    for k, v in (deferred_metrics(result, task_error) or {}).items():
                        if k:
                            samples.append(
                                _Sample(
                                    router_id="", metric=k, ts_ms=0,
                                    value=float(v), ok=False,
                                )
                            )
                except Exception:
                    logger.warning("deferred_metrics raised", exc_info=True)

            merged = self._merge_tags(tags)
            for s in samples:
                s.router_id = resolved_router
                s.ok = ok
                s.ts_ms = start_ts_ms
                s.tags = merged
                s.trace_id = resolved_trace
                self._enqueue(s)

        # ── propagate
        if task_error is not None:
            raise task_error

        return result  # type: ignore[return-value]

    # ── Report ───────────────────────────────────────────────────────────

    def report(
        self,
        *,
        router_id: str,
        metric: str,
        value: float = 0.0,
        ok: bool = True,
        trace_id: str = "",
        tags: dict[str, str] | None = None,
    ) -> None:
        """Send a sample outside of :meth:`execute` (fire-and-forget).

        Useful for async workflows or metrics derived from a response after
        the fact.
        """
        if not router_id or not metric:
            logger.warning(
                "report() called with missing router_id or metric"
            )
            return
        self._enqueue(
            _Sample(
                router_id=router_id,
                metric=metric,
                ts_ms=int(time.time() * 1000),
                value=value,
                ok=ok,
                tags=self._merge_tags(tags),
                trace_id=trace_id,
            )
        )

    # ── State queries ────────────────────────────────────────────────────

    def get_state(self, name: str) -> BreakerStatus | None:
        """Return the cached state of a single breaker, or ``None``."""
        with self._states_lock:
            s = self._states.get(name)
            if s is None:
                return None
            return BreakerStatus(name=name, state=s.state, allow_rate=s.allow_rate)

    def get_all_states(self) -> dict[str, BreakerStatus]:
        """Return a snapshot of all cached breaker states."""
        with self._states_lock:
            return {
                n: BreakerStatus(name=n, state=s.state, allow_rate=s.allow_rate)
                for n, s in self._states.items()
            }

    def get_breakers_metadata(self) -> list[BreakerMeta] | None:
        """Return a copy of cached breaker metadata, or ``None``."""
        with self._meta_lock:
            if self._breakers_meta is None:
                return None
            return [
                BreakerMeta(id=b.id, name=b.name, metadata=dict(b.metadata))
                for b in self._breakers_meta
            ]

    def get_routers_metadata(self) -> list[RouterMeta] | None:
        """Return a copy of cached router metadata, or ``None``."""
        with self._meta_lock:
            if self._routers_meta is None:
                return None
            return [
                RouterMeta(id=r.id, name=r.name, metadata=dict(r.metadata))
                for r in self._routers_meta
            ]

    @property
    def stats(self) -> SDKStats:
        """Snapshot of SDK health metrics."""
        with self._stats_lock:
            s = SDKStats(
                sse_connected=self._sse_connected,
                sse_reconnects=self._sse_reconnects,
                last_successful_flush=self._last_flush,
                last_sse_event=self._last_sse_event,
                flush_failures=self._flush_failures,
            )
        with self._dropped_lock:
            s.dropped_samples = self._dropped_samples
        s.buffer_size = self._queue.qsize()
        with self._states_lock:
            s.cached_breakers = len(self._states)
        return s

    def get_status(self) -> Status:
        """Fetch the project health summary from the API."""
        url = f"{self._base_url}/v1/projects/{self.project_id}/status"
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        resp = self._http.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return Status(
            open_count=data["open_count"],
            closed_count=data["closed_count"],
            last_eval_ms=data.get("last_eval_ms"),
        )

    # ── Metadata API (public, used by metadata sync internally) ──────────

    def list_breakers_metadata(
        self, etag: str = ""
    ) -> tuple[list[BreakerMeta] | None, str]:
        """Fetch breaker metadata from the API.

        Returns ``(breakers, new_etag)`` or ``(None, old_etag)`` on
        304 Not Modified.

        Raises:
            UnauthorizedError: On 401 or 403.
        """
        url = f"{self._base_url}/v1/projects/{self.project_id}/breakers/metadata"
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if etag:
            headers["If-None-Match"] = etag

        resp = self._http.get(url, headers=headers)
        if resp.status_code == 304:
            return None, etag
        if resp.status_code in (401, 403):
            raise UnauthorizedError("unauthorized", status=resp.status_code)
        resp.raise_for_status()

        data = resp.json()
        breakers = [
            BreakerMeta(id=b["id"], name=b["name"], metadata=b.get("metadata") or {})
            for b in data.get("breakers", [])
        ]
        return breakers, resp.headers.get("etag", "")

    def list_routers_metadata(
        self, etag: str = ""
    ) -> tuple[list[RouterMeta] | None, str]:
        """Fetch router metadata from the API.

        Returns ``(routers, new_etag)`` or ``(None, old_etag)`` on
        304 Not Modified.

        Raises:
            UnauthorizedError: On 401 or 403.
        """
        url = f"{self._base_url}/v1/projects/{self.project_id}/routers/metadata"
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if etag:
            headers["If-None-Match"] = etag

        resp = self._http.get(url, headers=headers)
        if resp.status_code == 304:
            return None, etag
        if resp.status_code in (401, 403):
            raise UnauthorizedError("unauthorized", status=resp.status_code)
        resp.raise_for_status()

        data = resp.json()
        routers = [
            RouterMeta(id=r["id"], name=r["name"], metadata=r.get("metadata") or {})
            for r in data.get("routers", [])
        ]
        return routers, resp.headers.get("etag", "")

    # ── Internal: breaker gating ─────────────────────────────────────────

    def _check_breakers(self, breakers: list[str]) -> None:
        if not breakers:
            return

        min_allow_rate = 1.0
        with self._states_lock:
            for name in breakers:
                state = self._states.get(name)
                if state is None:
                    continue
                if state.state == "open":
                    raise BreakerOpenError(name)
                if state.state == "half_open" and state.allow_rate < min_allow_rate:
                    min_allow_rate = state.allow_rate

        if min_allow_rate < 1.0 and random.random() >= min_allow_rate:
            raise BreakerOpenError()

    @staticmethod
    def _is_ok(
        error: Exception | None,
        ignore_errors: list[type[Exception]] | None,
        error_evaluator: Callable[[Exception], bool] | None,
    ) -> bool:
        if error is None:
            return True
        if error_evaluator is not None:
            return not error_evaluator(error)
        if ignore_errors:
            if isinstance(error, tuple(ignore_errors)):
                return True
        return False

    # ── Internal: metrics resolution ─────────────────────────────────────

    @staticmethod
    def _resolve_metrics(
        metrics: dict[str, Any], duration_ms: float
    ) -> list[_Sample]:
        samples: list[_Sample] = []
        for key, value in metrics.items():
            if not key:
                continue

            if value is Latency:
                resolved = duration_ms
            elif callable(value):
                try:
                    resolved = float(value())
                except Exception:
                    logger.warning(
                        "metric closure raised for %r", key, exc_info=True
                    )
                    continue
            elif isinstance(value, (int, float)):
                resolved = float(value)
            else:
                logger.warning(
                    "unsupported metric type %s for %r",
                    type(value).__name__, key,
                )
                continue

            samples.append(
                _Sample(router_id="", metric=key, ts_ms=0, value=resolved, ok=False)
            )
        return samples

    def _merge_tags(self, tags: dict[str, str] | None) -> dict[str, str] | None:
        if not tags and not self._global_tags:
            return None
        if not tags:
            return dict(self._global_tags)
        if not self._global_tags:
            return tags
        return {**self._global_tags, **tags}

    # ── Internal: sample buffer ──────────────────────────────────────────

    def _enqueue(self, sample: _Sample) -> None:
        try:
            self._queue.put_nowait(sample)
        except queue.Full:
            with self._dropped_lock:
                self._dropped_samples += 1

    # ── Internal: SSE listener ───────────────────────────────────────────

    def _sse_listener(self) -> None:
        if not self._api_key:
            return

        url = f"{self._base_url}/v1/projects/{self.project_id}/breakers/state:stream"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }

        consecutive_failures = 0

        while not self._shutdown.is_set():
            try:
                with httpx.Client(http2=False, timeout=None) as sse_http:
                    with sse_http.stream("GET", url, headers=headers) as resp:
                        resp.raise_for_status()
                        consecutive_failures = 0
                        for event in parse_sse_stream(resp.iter_lines()):
                            if self._shutdown.is_set():
                                return
                            try:
                                data = json.loads(event.data)
                            except json.JSONDecodeError:
                                logger.error(
                                    "bad SSE payload: %s", event.data
                                )
                                continue

                            allow_rate = 0.0
                            if data.get("allow_rate") is not None:
                                allow_rate = float(data["allow_rate"])
                            elif data.get("state") == "half_open":
                                logger.warning(
                                    "null allow_rate for half_open breaker %s",
                                    data.get("breaker"),
                                )

                            self._update_breaker_state(
                                data["breaker"], data["state"], allow_rate
                            )

                            with self._stats_lock:
                                self._sse_connected = True
                                self._last_sse_event = datetime.now(tz=timezone.utc)

                            self._sse_ready.set()

            except Exception:
                if self._shutdown.is_set():
                    return
                consecutive_failures += 1
                with self._stats_lock:
                    self._sse_reconnects += 1
                    self._sse_connected = False
                backoff_idx = min(
                    consecutive_failures - 1, len(_SSE_RECONNECT_BACKOFFS) - 1
                )
                delay = _SSE_RECONNECT_BACKOFFS[backoff_idx]
                logger.warning(
                    "SSE connection lost, reconnecting in %ds", delay,
                    exc_info=True,
                )
                if self._shutdown.wait(timeout=delay):
                    return

    def _update_breaker_state(
        self, name: str, new_state: str, allow_rate: float
    ) -> None:
        with self._states_lock:
            old = self._states.get(name)
            old_state = old.state if old else ""
            self._states[name] = _BreakerState(
                state=new_state, allow_rate=allow_rate
            )

        logger.info(
            "breaker %s: %s → %s (allow_rate=%.2f)",
            name, old_state or "(new)", new_state, allow_rate,
        )

        if old_state and old_state != new_state and self._on_state_change:
            try:
                self._on_state_change(name, old_state, new_state)
            except Exception:
                logger.warning("on_state_change callback raised", exc_info=True)

    # ── Internal: flusher ────────────────────────────────────────────────

    def _flusher(self) -> None:
        batch: list[_Sample] = []

        while True:
            try:
                entry = self._queue.get(timeout=_FLUSH_INTERVAL)
                if entry is None:
                    # Shutdown sentinel — drain remaining items
                    while not self._queue.empty():
                        try:
                            e = self._queue.get_nowait()
                            if e is not None:
                                batch.append(e)
                        except queue.Empty:
                            break
                    if batch:
                        self._send_batch(batch)
                    return

                batch.append(entry)
                if len(batch) >= _BATCH_SIZE:
                    self._spawn_send(batch)
                    batch = []

            except queue.Empty:
                if batch:
                    self._spawn_send(batch)
                    batch = []
                if self._shutdown.is_set():
                    return

    def _spawn_send(self, batch: list[_Sample]) -> None:
        t = threading.Thread(
            target=self._send_batch, args=(batch,),
            name="tripswitch-send", daemon=True,
        )
        t.start()
        self._send_workers.append(t)

    def _send_batch(self, batch: list[_Sample]) -> None:
        if not batch:
            return

        payload = json.dumps({"samples": [s.to_dict() for s in batch]}).encode()
        compressed = gzip.compress(payload)

        timestamp_ms = str(int(time.time() * 1000))

        signature = ""
        if self._ingest_secret:
            try:
                secret_bytes = bytes.fromhex(self._ingest_secret)
            except ValueError:
                logger.error("invalid ingest_secret (not valid hex)")
                with self._dropped_lock:
                    self._dropped_samples += len(batch)
                return
            message = timestamp_ms.encode() + b"." + compressed
            mac = hmac.new(secret_bytes, message, hashlib.sha256)
            signature = "v1=" + mac.hexdigest()

        url = f"{self._base_url}/v1/projects/{self.project_id}/ingest"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "X-EB-Timestamp": timestamp_ms,
        }
        if signature:
            headers["X-EB-Signature"] = signature

        for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
            if self._shutdown.is_set():
                with self._dropped_lock:
                    self._dropped_samples += len(batch)
                return

            if attempt > 0:
                time.sleep(_BACKOFF_SCHEDULE[attempt - 1])

            try:
                resp = self._http.post(url, content=compressed, headers=headers)
                if 200 <= resp.status_code < 300:
                    with self._stats_lock:
                        self._last_flush = datetime.now(tz=timezone.utc)
                    return
                logger.error(
                    "ingest failed: status=%d attempt=%d",
                    resp.status_code, attempt + 1,
                )
            except Exception:
                if not self._shutdown.is_set():
                    logger.error("ingest request failed", exc_info=True)

        # All retries exhausted
        logger.error("dropping %d samples after retries exhausted", len(batch))
        with self._dropped_lock:
            self._dropped_samples += len(batch)
        with self._stats_lock:
            self._flush_failures += 1

    # ── Internal: metadata sync ──────────────────────────────────────────

    def _metadata_sync(self) -> None:
        if self._refresh_metadata():
            return
        while not self._shutdown.wait(timeout=self._meta_sync_interval):
            if self._refresh_metadata():
                return

    def _refresh_metadata(self) -> bool:
        """Fetch and cache metadata.  Returns True to stop syncing."""
        with self._meta_lock:
            b_etag = self._breakers_etag
            r_etag = self._routers_etag

        # Breakers
        try:
            breakers, new_b_etag = self.list_breakers_metadata(etag=b_etag)
            if breakers is not None:
                with self._meta_lock:
                    self._breakers_meta = breakers
                    self._breakers_etag = new_b_etag
        except UnauthorizedError:
            logger.warning("metadata sync stopping: auth failure")
            return True
        except Exception:
            logger.warning("failed to refresh breakers metadata", exc_info=True)

        # Routers
        try:
            routers, new_r_etag = self.list_routers_metadata(etag=r_etag)
            if routers is not None:
                with self._meta_lock:
                    self._routers_meta = routers
                    self._routers_etag = new_r_etag
        except UnauthorizedError:
            logger.warning("metadata sync stopping: auth failure")
            return True
        except Exception:
            logger.warning("failed to refresh routers metadata", exc_info=True)

        return False

    # ── Internal: helpers ────────────────────────────────────────────────

    def _start_thread(self, target: Callable[[], None], name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)
