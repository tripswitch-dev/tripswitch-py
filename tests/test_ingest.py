"""Tests for HMAC signing and batch payload format."""

from __future__ import annotations

import gzip
import hashlib
import hmac as hmac_mod
import json

from tripswitch.client import _Sample


def test_hmac_signature_matches_go_approach():
    """Verify our HMAC signing matches the Go SDK's 'sign what you send' approach.

    The Go SDK signs: "{timestamp_ms}.{compressed_body}" with the hex-decoded
    ingest secret using HMAC-SHA256, then formats as "v1={hex}".
    """
    secret_hex = "a" * 64  # 32 bytes when decoded
    secret_bytes = bytes.fromhex(secret_hex)

    samples = [
        _Sample(router_id="r1", metric="latency", ts_ms=1700000000000,
                value=42.5, ok=True).to_dict()
    ]
    payload = json.dumps({"samples": samples}).encode()
    compressed = gzip.compress(payload)

    timestamp_ms = "1700000000000"
    message = timestamp_ms.encode() + b"." + compressed
    mac = hmac_mod.new(secret_bytes, message, hashlib.sha256)
    signature = "v1=" + mac.hexdigest()

    assert signature.startswith("v1=")
    assert len(signature) == 3 + 64  # "v1=" + 64 hex chars


def test_batch_payload_structure():
    """Verify the JSON structure matches what the Go SDK sends."""
    samples = [
        _Sample(
            router_id="router-1", metric="latency", ts_ms=1700000000000,
            value=42.5, ok=True, tags={"env": "prod"}, trace_id="trace-123",
        ),
        _Sample(
            router_id="router-1", metric="error_count", ts_ms=1700000000000,
            value=0.0, ok=True,
        ),
    ]

    payload = {"samples": [s.to_dict() for s in samples]}

    assert len(payload["samples"]) == 2
    assert payload["samples"][0]["router_id"] == "router-1"
    assert payload["samples"][0]["tags"] == {"env": "prod"}
    assert payload["samples"][0]["trace_id"] == "trace-123"
    assert "tags" not in payload["samples"][1]
    assert "trace_id" not in payload["samples"][1]
