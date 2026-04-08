# tripswitch-py

[![PyPI](https://img.shields.io/pypi/v/tripswitch-py)](https://pypi.org/project/tripswitch-py/)
[![Python](https://img.shields.io/pypi/pyversions/tripswitch-py)](https://pypi.org/project/tripswitch-py/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

Official Python SDK for [Tripswitch](https://tripswitch.dev) — a circuit breaker management service.

This SDK conforms to the [Tripswitch SDK Contract v0.2](https://tripswitch.dev/docs/sdk-contract).

## Features

- **Real-time state sync** via Server-Sent Events (SSE)
- **Automatic sample reporting** with buffered, batched uploads
- **Fail-open by default** — your app stays available even if Tripswitch is unreachable
- **Thread-safe** — one client per project, safe for concurrent use
- **Context manager support** for automatic lifecycle management

## Installation

```bash
pip install tripswitch-py
```

**Requires Python 3.10+**

## Authentication

Tripswitch uses a two-tier authentication model:

### Runtime Credentials (SDK)

For SDK initialization, you need two credentials from **Project Settings > SDK Keys**:

| Credential | Prefix | Purpose |
|------------|--------|---------|
| **Project Key** | `eb_pk_` | SSE connection and state reads |
| **Ingest Secret** | `ik_` | HMAC-signed sample ingestion |

```python
import tripswitch

ts = tripswitch.Client(
    "proj_abc123",
    api_key="eb_pk_...",
    ingest_secret="ik_...",
)
```

### Admin Credentials (Management API)

For management and automation tasks, use an **Admin Key** from **Organization Settings > Admin Keys**:

| Credential | Prefix | Purpose |
|------------|--------|---------|
| **Admin Key** | `eb_admin_` | Organization-scoped management operations |

Admin keys are used with the [Admin Client](#admin-client) for creating projects, managing breakers, and other administrative tasks — not for runtime SDK usage.

## Quick Start

```python
import httpx
import tripswitch

with tripswitch.Client(
    "proj_abc123",
    api_key="eb_pk_...",
    ingest_secret="ik_...",
) as ts:
    # Wrap operations with circuit breaker
    try:
        resp = ts.execute(
            lambda: httpx.get("https://api.example.com/data"),
            breakers=["external-api"],
            router="my-router-id",
            metrics={"latency": tripswitch.Latency},
        )
        # Process response...
    except tripswitch.BreakerOpenError:
        # Circuit is open — return cached/fallback response
        print("circuit open, using fallback")
```

## Configuration Options

### Client Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `api_key` | Project key (`eb_pk_`) for SSE authentication | `""` |
| `ingest_secret` | Ingest secret (`ik_`) for HMAC-signed sample reporting | `""` |
| `fail_open` | Allow traffic when Tripswitch is unreachable | `True` |
| `base_url` | Override API endpoint | `https://api.tripswitch.dev` |
| `on_state_change` | Callback `(name, old_state, new_state)` on breaker transitions | `None` |
| `trace_id_extractor` | Zero-arg callable returning a trace ID for each sample | `None` |
| `global_tags` | Tags applied to all samples | `None` |
| `metadata_sync_interval` | Interval (seconds) for refreshing breaker/router metadata. Set `<= 0` to disable. | `30.0` |
| `timeout` | Max seconds to wait for initial SSE sync | `None` |

### Execute Options

| Parameter | Description |
|-----------|-------------|
| `breakers` | Breaker names to check before executing (any open raises `BreakerOpenError`). If omitted, no gating is performed. |
| `select_breakers` | Dynamically select breakers based on cached metadata. Mutually exclusive with `breakers`. |
| `router` | Router ID for sample routing. If omitted, no samples are emitted. |
| `select_router` | Dynamically select a router based on cached metadata. Mutually exclusive with `router`. |
| `metrics` | Metrics to report (`Latency` sentinel, `Callable[[], float]`, or numeric values) |
| `deferred_metrics` | Extract metrics from the task's return value (e.g., token counts from API responses) |
| `tags` | Per-call tags (merged with `global_tags`; call-site wins) |
| `ignore_errors` | Exception types that should not count as failures |
| `error_evaluator` | Custom function to determine if an exception is a failure (takes precedence over `ignore_errors`) |
| `trace_id` | Explicit trace ID (takes precedence over `trace_id_extractor`) |

### Error Classification

Every sample includes an `ok` field indicating whether the task succeeded or failed. This is determined by the following evaluation order:

1. **`error_evaluator`** — if set, takes precedence. Return `True` if the error **is a failure**; `False` if it should be treated as success.

   ```python
   # Only count 5xx as failures; 4xx are "expected" errors
   def eval_error(err: Exception) -> bool:
       if isinstance(err, httpx.HTTPStatusError):
           return err.response.status_code >= 500
       return True

   ts.execute(task, error_evaluator=eval_error, ...)
   ```

2. **`ignore_errors`** — if the task error is an instance of any listed type, it is **not** counted as a failure.

   ```python
   # KeyError is expected, don't count it
   ts.execute(task, ignore_errors=[KeyError], ...)
   ```

3. **Default** — any exception is a failure; no exception is success.

## API Reference

### Client

```python
class Client:
    def __init__(
        self,
        project_id: str,
        *,
        api_key: str = "",
        ingest_secret: str = "",
        fail_open: bool = True,
        base_url: str = "https://api.tripswitch.dev",
        on_state_change: Callable[[str, str, str], None] | None = None,
        trace_id_extractor: Callable[[], str] | None = None,
        global_tags: dict[str, str] | None = None,
        metadata_sync_interval: float = 30.0,
        timeout: float | None = None,
    ): ...
```

Use as a context manager for automatic lifecycle management. Starts background threads for SSE state sync and sample flushing, and blocks until the initial SSE sync completes.

### execute

```python
def execute(
    self,
    task: Callable[[], T],
    *,
    breakers: list[str] | None = None,
    router: str | None = None,
    metrics: dict[str, Any] | None = None,
    ...
) -> T
```

Runs a task end-to-end: checks breaker state, executes the task, and reports samples — all in one call.

- Use `breakers` to gate execution on breaker state (omit for pass-through)
- Use `router` to specify where samples go (omit for no sample emission)
- Use `metrics` to specify what values to report

Raises `BreakerOpenError` if any specified breaker is open.

### Latency

```python
class Latency: ...
```

Sentinel value for `metrics` that instructs the SDK to automatically compute and report task duration in milliseconds. Pass the **class itself**, not an instance:

```python
ts.execute(task, metrics={"latency": tripswitch.Latency}, router="my-router")
```

### close

```python
def close(self, timeout: float = 5.0) -> None
```

Gracefully shuts down the client. The timeout controls how long to wait for buffered samples to flush.

### stats

```python
@property
def stats(self) -> SDKStats
```

Returns a snapshot of SDK health metrics:

```python
@dataclass
class SDKStats:
    dropped_samples: int        # Samples dropped due to buffer overflow
    buffer_size: int            # Current buffer occupancy
    sse_connected: bool         # SSE connection status
    sse_reconnects: int         # Count of SSE reconnections
    last_successful_flush: datetime | None
    last_sse_event: datetime | None
    flush_failures: int         # Batches dropped after retry exhaustion
    cached_breakers: int        # Number of breakers in local state cache
```

### Breaker State Inspection

These methods expose the SDK's local breaker cache for debugging, logging, and health checks. For gating traffic on breaker state, use `execute` with `breakers` — it handles state checks, throttling, and sample reporting together.

```python
def get_state(self, name: str) -> BreakerStatus | None
def get_all_states(self) -> dict[str, BreakerStatus]
```

```python
# Debug: why is checkout rejecting requests?
status = ts.get_state("checkout")
if status:
    print(f"checkout breaker: state={status.state} allow_rate={status.allow_rate:.2f}")

# Health endpoint: expose all breaker states to monitoring
for name, status in ts.get_all_states().items():
    print(f"breaker {name}: {status.state}")
```

### Error Handling

```python
class BreakerOpenError(TripSwitchError): ...
class ConflictingOptionsError(TripSwitchError): ...
class MetadataUnavailableError(TripSwitchError): ...
```

| Error | Cause |
|-------|-------|
| `BreakerOpenError` | A specified breaker is open or request was throttled in half-open state |
| `ConflictingOptionsError` | Mutually exclusive options used (e.g. `breakers` + `select_breakers`) |
| `MetadataUnavailableError` | Selector used but metadata cache hasn't been populated yet |

```python
try:
    result = ts.execute(
        task,
        breakers=["my-breaker"],
        router="my-router",
        metrics={"latency": tripswitch.Latency},
    )
except tripswitch.BreakerOpenError:
    # Breaker is open or request was throttled
    return fallback_value
```

## Custom Metric Values

`Latency` is a convenience sentinel that auto-computes task duration in milliseconds. You can report **any metric with any value**:

```python
ts.execute(
    task,
    router="my-router",
    metrics={
        # Auto-computed latency
        "latency": tripswitch.Latency,

        # Static numeric values
        "response_bytes": 4096,
        "queue_depth": 42.5,

        # Dynamic values via closure (called after task completes)
        "memory_mb": lambda: psutil.Process().memory_info().rss / 1024 / 1024,
    },
)
```

### Deferred Metrics

Use `deferred_metrics` to extract metrics from the task's return value — useful when the interesting values are in the response (e.g., token counts from LLM APIs):

```python
result = ts.execute(
    lambda: anthropic_client.messages.create(...),
    breakers=["anthropic-spend"],
    router="llm-router",
    metrics={"latency": tripswitch.Latency},
    deferred_metrics=lambda res, err: {
        "prompt_tokens": float(res.usage.input_tokens),
        "completion_tokens": float(res.usage.output_tokens),
    } if res else None,
)
```

### Dynamic Selection

Use `select_breakers` and `select_router` to choose breakers or routers at runtime based on cached metadata:

```python
# Gate on breakers matching a metadata property
result = ts.execute(
    task,
    select_breakers=lambda breakers: [
        b.name for b in breakers if b.metadata.get("region") == "us-east-1"
    ],
)

# Route samples to a router matching a metadata property
result = ts.execute(
    task,
    select_router=lambda routers: next(
        (r.id for r in routers if r.metadata.get("env") == "production"), ""
    ),
    metrics={"latency": tripswitch.Latency},
)
```

### report

```python
def report(
    self,
    *,
    router_id: str,
    metric: str,
    value: float = 0.0,
    ok: bool = True,
    trace_id: str = "",
    tags: dict[str, str] | None = None,
) -> None
```

Send a sample independently of `execute`. Use this for async workflows, result-derived metrics, or fire-and-forget reporting:

```python
ts.report(router_id="llm-router", metric="total_tokens", value=1500.0, ok=True)
ts.report(
    router_id="worker-metrics",
    metric="queue_depth",
    value=float(queue_len),
    ok=True,
    tags={"worker": "processor-1"},
)
```

## Circuit Breaker States

| State | Behavior |
|-------|----------|
| `closed` | All requests allowed, results reported |
| `open` | All requests rejected with `BreakerOpenError` |
| `half_open` | Requests throttled based on `allow_rate` (e.g., 20% allowed) |

## How It Works

1. **State Sync**: The client maintains a local cache of breaker states, updated in real-time via SSE
2. **Execute Check**: Each `execute` call checks the local cache (no network call)
3. **Sample Reporting**: Results are buffered and batched (500 samples or 15s, whichever comes first)
4. **Graceful Degradation**: If Tripswitch is unreachable, the client fails open by default

## Admin Client

The `admin` module provides a client for management and automation tasks. This is separate from the runtime SDK and uses organization-scoped admin keys.

```python
from tripswitch.admin import AdminClient

with AdminClient(api_key="eb_admin_...") as client:
    # List all workspaces
    workspaces = client.list_workspaces()

    # Create a workspace
    workspace = client.create_workspace(CreateWorkspaceInput(name="acme", slug="acme"))

    # Get workspace details
    workspace = client.get_workspace("ws_abc123")

    # Update a workspace
    workspace = client.update_workspace("ws_abc123", UpdateWorkspaceInput(name="acme-corp"))

    # Delete a workspace (requires name confirmation as a safety guard)
    client.delete_workspace("ws_abc123", confirm_name="acme-corp")

    # List all projects (optionally filter by workspace)
    projects = client.list_projects()
    projects = client.list_projects(workspace_id="ws_abc123")

    # Create a project (optionally assign to a workspace)
    project = client.create_project(CreateProjectInput(name="prod-payments"))
    project = client.create_project(CreateProjectInput(name="prod-payments", workspace_id="ws_abc123"))

    # Get project details
    project = client.get_project("proj_abc123")

    # Delete a project (requires name confirmation as a safety guard)
    client.delete_project("proj_abc123", confirm_name="prod-payments")

    # List breakers
    breakers = client.list_breakers("proj_abc123")

    # Create a breaker
    breaker = client.create_breaker(
        "proj_abc123",
        CreateBreakerInput(
            name="api-latency",
            metric="latency_ms",
            kind="p95",
            op="gt",
            threshold=500,
        ),
    )
```

**Note:** Admin keys (`eb_admin_`) are for management operations only. For runtime SDK usage, use project keys (`eb_pk_`) as shown in [Quick Start](#quick-start).

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

[Apache License 2.0](LICENSE)
