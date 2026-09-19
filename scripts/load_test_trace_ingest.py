#!/usr/bin/env python3
"""Load-test OTLP trace ingest against a running API."""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import httpx


def _build_otlp_batch(call_short_id: str, batch_idx: int) -> bytes:
    span_id = f"{batch_idx:016x}"[:16]
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "a" * 32,
                                "spanId": span_id,
                                "name": "stt",
                                "attributes": [
                                    {"key": "efficientai.call_short_id", "value": {"stringValue": call_short_id}},
                                    {"key": "gen_ai.operation.name", "value": {"stringValue": "stt"}},
                                    {"key": "metrics.ttfb", "value": {"doubleValue": 0.12}},
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


def _run_call(
    *,
    base_url: str,
    api_key: str,
    workspace_id: str,
    duration_seconds: int,
    interval_seconds: float,
) -> List[float]:
    headers = {
        "X-API-Key": api_key,
        "X-Workspace-Id": workspace_id,
        "Content-Type": "application/json",
    }
    latencies: List[float] = []
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        session = client.post("/api/v1/observability/traces/sessions", headers=headers, json={"transport": "webrtc"})
        session.raise_for_status()
        call_short_id = session.json()["call_short_id"]
        headers["X-EfficientAI-Call-Short-Id"] = call_short_id
        deadline = time.monotonic() + duration_seconds
        batch_idx = 0
        while time.monotonic() < deadline:
            body = _build_otlp_batch(call_short_id, batch_idx)
            start = time.perf_counter()
            resp = client.post("/api/v1/observability/traces", headers=headers, content=body)
            resp.raise_for_status()
            latencies.append((time.perf_counter() - start) * 1000)
            batch_idx += 1
            time.sleep(interval_seconds)
        client.post(f"/api/v1/observability/traces/sessions/{call_short_id}/close", headers=headers)
    return latencies


def main() -> None:
    parser = argparse.ArgumentParser(description="OTLP trace ingest load test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--concurrent-calls", type=int, default=20)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args()

    all_latencies: List[float] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.concurrent_calls) as pool:
        futures = [
            pool.submit(
                _run_call,
                base_url=args.base_url,
                api_key=args.api_key,
                workspace_id=args.workspace_id,
                duration_seconds=args.duration_seconds,
                interval_seconds=args.interval_seconds,
            )
            for _ in range(args.concurrent_calls)
        ]
        for future in as_completed(futures):
            with lock:
                all_latencies.extend(future.result())

    if not all_latencies:
        print("No samples collected")
        return
    sorted_lat = sorted(all_latencies)
    p50 = statistics.median(sorted_lat)
    p95 = sorted_lat[int(0.95 * (len(sorted_lat) - 1))]
    print(f"calls={args.concurrent_calls} samples={len(all_latencies)}")
    print(f"ack_p50_ms={p50:.1f} ack_p95_ms={p95:.1f}")


if __name__ == "__main__":
    main()
