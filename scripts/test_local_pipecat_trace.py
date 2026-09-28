#!/usr/bin/env python3
"""
End-to-end local test for call trace ingest (simulates Pipecat export).

  1. POST /observability/traces/sessions
  2. POST /observability/traces (OTLP JSON)
  3. POST /sessions/{call_short_id}/close
  4. GET /observability/traces

Usage:
  export EFFICIENTAI_API_KEY="<from Workspace → API keys>"
  export EFFICIENTAI_WORKSPACE_ID="<workspace-uuid>"
  uv run python scripts/test_local_pipecat_trace.py

Optional:
  EFFICIENTAI_BASE_URL=http://localhost:8000
  EFFICIENTAI_TRANSPORT=webrtc
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

BASE = os.environ.get("EFFICIENTAI_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("EFFICIENTAI_API_KEY", "").strip()
WORKSPACE_ID = os.environ.get("EFFICIENTAI_WORKSPACE_ID", "").strip()
TRANSPORT = os.environ.get("EFFICIENTAI_TRANSPORT", "webrtc").strip()
TRACES = "/api/v1/observability/traces"


def _headers() -> dict[str, str]:
    h = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    if WORKSPACE_ID:
        h["X-Workspace-Id"] = WORKSPACE_ID
    return h


def _require_env() -> None:
    missing = [n for n, v in [
        ("EFFICIENTAI_API_KEY", API_KEY),
        ("EFFICIENTAI_WORKSPACE_ID", WORKSPACE_ID),
    ] if not v]
    if missing:
        print("Missing required environment variables:", ", ".join(missing))
        sys.exit(1)


def _otlp_json_payload(call_short_id: str) -> dict:
    trace_id = uuid.uuid4().hex

    def span(name: str, span_id: str, op: str, turn: int, ttfb_s: float) -> dict:
        return {
            "traceId": trace_id,
            "spanId": span_id,
            "name": name,
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": op}},
                {"key": "turn.number", "value": {"intValue": str(turn)}},
                {"key": "metrics.ttfb", "value": {"doubleValue": ttfb_s}},
                {"key": "efficientai.call_short_id", "value": {"stringValue": call_short_id}},
                {"key": "efficientai.workspace_id", "value": {"stringValue": WORKSPACE_ID}},
            ],
        }

    return {
        "resourceSpans": [{
            "scopeSpans": [{
                "spans": [
                    span("stt", "a1", "stt", 1, 0.12),
                    span("llm", "a2", "chat", 1, 0.38),
                    span("tts", "a3", "tts", 1, 0.21),
                ],
            }],
        }],
    }


def main() -> int:
    _require_env()
    client = httpx.Client(base_url=BASE, timeout=30.0)
    headers = _headers()

    print(f"→ Health: {BASE}/health")
    health = client.get("/health")
    health.raise_for_status()
    print(f"  {health.json()}")

    print(f"\n→ POST {TRACES}/sessions (transport={TRANSPORT})")
    session_resp = client.post(
        f"{TRACES}/sessions",
        headers=headers,
        json={"transport": TRANSPORT},
    )
    if session_resp.status_code >= 400:
        print(f"  ERROR {session_resp.status_code}: {session_resp.text}")
        return 1
    session = session_resp.json()
    call_short_id = session["call_short_id"]
    trace_id = session["trace_id"]
    print(f"  call_short_id={call_short_id}  trace_id={trace_id}")
    print(f"  otlp_endpoint={session['otel_correlation']['otlp_endpoint']}")

    print(f"\n→ POST {TRACES} (simulating Pipecat export)")
    otlp_headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
        "X-EfficientAI-Call-Short-Id": call_short_id,
        "X-Workspace-Id": WORKSPACE_ID,
    }
    otlp_resp = client.post(
        TRACES,
        headers=otlp_headers,
        content=json.dumps(_otlp_json_payload(call_short_id)),
    )
    if otlp_resp.status_code >= 400:
        print(f"  ERROR {otlp_resp.status_code}: {otlp_resp.text}")
        return 1
    otlp = otlp_resp.json()
    print(f"  accepted_spans={otlp['accepted_spans']} correlated={otlp['correlated']}")

    print(f"\n→ POST {TRACES}/sessions/{call_short_id}/close")
    close_resp = client.post(
        f"{TRACES}/sessions/{call_short_id}/close",
        headers={"X-API-Key": API_KEY, "X-Workspace-Id": WORKSPACE_ID},
    )
    close_resp.raise_for_status()
    print(f"  status={close_resp.json()['status']}")

    print(f"\n→ GET {TRACES}?status=closed")
    list_resp = client.get(
        TRACES,
        headers={"X-API-Key": API_KEY, "X-Workspace-Id": WORKSPACE_ID},
        params={"status": "closed", "limit": 5},
    )
    list_resp.raise_for_status()
    items = list_resp.json().get("items") or []
    match = next((t for t in items if t.get("call_short_id") == call_short_id), None)
    if not match:
        print("  WARNING: trace not found in list (check workspace scope)")
        return 1
    print(f"  found trace turn_count={match.get('turn_count')}")

    print(f"\n→ GET {TRACES}/{trace_id}")
    detail = client.get(
        f"{TRACES}/{trace_id}",
        headers={"X-API-Key": API_KEY, "X-Workspace-Id": WORKSPACE_ID},
    )
    detail.raise_for_status()
    d = detail.json()
    print(f"  turns={len(d.get('turns') or [])} otel_spans={len(d.get('otel_spans') or [])}")

    print("\n✅ Local call trace path OK.")
    print(f"   Open Call Traces UI and look for call_short_id {call_short_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
