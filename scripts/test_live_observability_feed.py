#!/usr/bin/env python3
"""Simulate an ongoing Pipecat call and stream the live transcript feed.

Posts incremental events to POST /api/v1/observability/live/events while
subscribing to GET /api/v1/observability/calls/{call_short_id}/live-events (SSE).

Usage:
  export EFFICIENTAI_API_KEY="..."   # Settings → API Keys
  export EFFICIENTAI_WORKSPACE_ID="..."  # optional; auto-resolved from /workspaces
  python3 scripts/test_live_observability_feed.py

  # Or login instead of API key:
  export EFFICIENTAI_EMAIL="you@example.com"
  export EFFICIENTAI_PASSWORD="..."
  python3 scripts/test_live_observability_feed.py

Optional:
  BASE_URL=http://localhost:8000 TURN_DELAY_SEC=3 NUM_TURNS=4 python3 ...
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
API_PREFIX = "/api/v1"
TURN_DELAY_SEC = float(os.environ.get("TURN_DELAY_SEC", "3"))
NUM_TURNS = int(os.environ.get("NUM_TURNS", "4"))
_PLACEHOLDER_KEYS = frozenset(
    {
        "",
        "your-api-key",
        "your-key-from-settings",
        "changeme",
        "replace-me",
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    stream: bool = False,
):
    url = f"{BASE_URL}{path}"
    data = None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=req_headers, method=method)
    if stream:
        return urlopen(req, timeout=300)
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return resp.status, {}
            return resp.status, json.loads(raw)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401 and "Invalid API key" in detail:
            raise RuntimeError(
                f"{method} {path} failed HTTP 401: Invalid API key. "
                "Copy the full key from Settings → API Keys (shown only once at creation). "
                "If you regenerated the key, update EFFICIENTAI_API_KEY in your shell."
            ) from exc
        raise RuntimeError(f"{method} {path} failed HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc


def _auth_headers(api_key: str | None, bearer: str | None, workspace_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    elif bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    else:
        raise RuntimeError("Set EFFICIENTAI_API_KEY or EFFICIENTAI_EMAIL + EFFICIENTAI_PASSWORD")
    if workspace_id:
        headers["X-Workspace-Id"] = workspace_id
    return headers


def _login() -> str:
    email = os.environ.get("EFFICIENTAI_EMAIL", "").strip()
    password = os.environ.get("EFFICIENTAI_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Set EFFICIENTAI_API_KEY or EFFICIENTAI_EMAIL + EFFICIENTAI_PASSWORD")
    _, payload = _request(
        "POST",
        f"{API_PREFIX}/auth/login",
        body={"email": email, "password": password},
    )
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Login succeeded but no access_token in response")
    return token


def _resolve_workspace(headers: dict[str, str]) -> str:
    preset = os.environ.get("EFFICIENTAI_WORKSPACE_ID", "").strip()
    if preset:
        return preset
    _, payload = _request("GET", f"{API_PREFIX}/workspaces", headers=headers)
    workspaces = payload if isinstance(payload, list) else payload.get("items", [])
    if not workspaces:
        raise RuntimeError("No workspaces found; set EFFICIENTAI_WORKSPACE_ID")
    ws_id = workspaces[0].get("id")
    ws_name = workspaces[0].get("name", "unknown")
    print(f"Using workspace: {ws_name} ({ws_id})")
    return str(ws_id)


def _post_live_event(headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    _, body = _request("POST", f"{API_PREFIX}/observability/live/events", headers=headers, body=payload)
    return body


def _transcript_len(snap: dict[str, Any]) -> int:
    top = snap.get("live_transcript")
    if isinstance(top, list):
        return len(top)
    call_data = snap.get("call_data")
    if isinstance(call_data, dict):
        nested = call_data.get("live_transcript")
        if isinstance(nested, list):
            return len(nested)
    return 0


def _poll_call(headers: dict[str, str], call_short_id: str) -> dict[str, Any]:
    _, body = _request("GET", f"{API_PREFIX}/observability/calls/{call_short_id}", headers=headers)
    return body


class LiveFeedWatcher:
    """Subscribe to SSE live-events and print transcript turns as they arrive."""

    def __init__(self, headers: dict[str, str], call_short_id: str) -> None:
        self._headers = headers
        self._call_short_id = call_short_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.seen_turns = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        path = f"{API_PREFIX}/observability/calls/{self._call_short_id}/live-events"
        url = f"{BASE_URL}{path}"
        req = Request(url, headers={**self._headers, "Accept": "text/event-stream"}, method="GET")
        try:
            with urlopen(req, timeout=300) as resp:
                for raw_line in resp:
                    if self._stop.is_set():
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        turn = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    self.seen_turns += 1
                    role = turn.get("role", "?")
                    content = (turn.get("content") or "")[:120]
                    ts = turn.get("event_ts") or turn.get("timestamp") or ""
                    print(f"  [SSE feed] {role}: {content!r}  ({ts})", flush=True)
        except Exception as exc:  # noqa: BLE001 — background watcher
            if not self._stop.is_set():
                print(f"  [SSE feed] stream ended: {exc}", flush=True)


def _validate_api_key(api_key: str | None) -> None:
    if not api_key:
        return
    if api_key.lower() in _PLACEHOLDER_KEYS:
        raise RuntimeError(
            'EFFICIENTAI_API_KEY is still the placeholder "your-api-key". '
            "Paste the full key shown once when you created it in Settings → API Keys."
        )
    if len(api_key) < 20:
        raise RuntimeError(
            "EFFICIENTAI_API_KEY looks too short. Copy the full key from Settings → API Keys "
            "(not the key name/label)."
        )


def main() -> int:
    api_key = os.environ.get("EFFICIENTAI_API_KEY", "").strip() or None
    bearer = None
    _validate_api_key(api_key)
    if not api_key:
        print("Logging in with EFFICIENTAI_EMAIL...")
        bearer = _login()

    headers = _auth_headers(api_key, bearer, None)
    workspace_id = _resolve_workspace(headers)
    headers["X-Workspace-Id"] = workspace_id

    print(f"\n== Checking live feature flags ({BASE_URL}) ==")
    _, summary = _request("GET", f"{API_PREFIX}/observability/calls/summary", headers=headers)
    flags = summary.get("live_feature_flags") or {}
    print(json.dumps(flags, indent=2))
    if not flags.get("live_ingest_enabled"):
        print(
            "\nERROR: OBSERVABILITY_LIVE_INGEST_ENABLED is false on the API.\n"
            "Restart the api service with live flags enabled (see docker-compose.yml).\n",
            file=sys.stderr,
        )
        return 1

    call_id = f"pipecat-live-{int(time.time())}"
    seq = 0

    def next_event(event_type: str, payload: dict[str, Any], event_suffix: str) -> dict[str, Any]:
        nonlocal seq
        seq += 1
        return {
            "event_id": f"evt-{call_id}-{event_suffix}",
            "call_id": call_id,
            "event_type": event_type,
            "seq": seq,
            "event_ts": _now_iso(),
            "platform": "pipecat",
            "payload": payload,
        }

    print(f"\n== Starting simulated call: {call_id} ==")
    started = _post_live_event(
        headers,
        next_event("call.started", {"direction": "inbound", "startedAt": _now_iso()}, "start"),
    )
    call_short_id = started.get("call_short_id")
    trace_id = started.get("trace_id")
    print(f"  call_short_id: {call_short_id}")
    print(f"  trace_id:      {trace_id}")
    print(f"  UI:            {BASE_URL}/observability/calls/{call_short_id}")

    if not call_short_id:
        print("ERROR: ingest did not return call_short_id", file=sys.stderr)
        return 1

    watcher = LiveFeedWatcher(headers, call_short_id)
    print("\n== SSE live feed (open Observability UI — list auto-refreshes every 3s for live calls) ==")
    watcher.start()

    dialog = [
        ("turn.user", {"content": "Hello, can you hear me?"}),
        ("turn.assistant", {"content": "Yes, I can hear you clearly.", "latency": {"llm_ms": 380, "tts_ms": 210}}),
        ("turn.user", {"content": "What is the weather like today?"}),
        ("turn.assistant", {"content": "I do not have live weather data, but I can help you look it up.", "latency": {"llm_ms": 520, "tts_ms": 190}}),
        ("turn.user", {"content": "Thanks, that is all."}),
        ("turn.assistant", {"content": "You're welcome. Goodbye!", "latency": {"llm_ms": 290, "tts_ms": 160}}),
    ]
    turns_to_send = dialog[: NUM_TURNS * 2]

    for idx, (event_type, payload) in enumerate(turns_to_send):
        time.sleep(TURN_DELAY_SEC)
        ack = _post_live_event(headers, next_event(event_type, payload, f"turn-{idx + 1}"))
        role = event_type.split(".")[-1]
        snippet = (payload.get("content") or "")[:80]
        print(f"\n  [posted] seq={seq} {role}: {snippet!r}  duplicate={ack.get('duplicate')}", flush=True)

        snap = _poll_call(headers, call_short_id)
        last_ts = snap.get("last_live_event_ts")
        print(
            f"  [poll]   call_event={snap.get('call_event')} "
            f"turns={_transcript_len(snap)} last_live_event_ts={last_ts}",
            flush=True,
        )

        if flags.get("live_aggregates_enabled"):
            _, metrics = _request(
                "GET",
                f"{API_PREFIX}/observability/live/metrics/latency?platform=pipecat",
                headers=headers,
            )
            sample_count = metrics.get("windows", {}).get("300s", {}).get("sample_count", 0)
            p90 = metrics.get("windows", {}).get("300s", {}).get("metrics", {}).get("llm_ms", {}).get("p90")
            print(f"  [metrics] rolling 300s samples={sample_count} llm_p90={p90}", flush=True)

    time.sleep(TURN_DELAY_SEC)
    ended = _post_live_event(
        headers,
        next_event("call.ended", {"endedAt": _now_iso(), "status": "ended"}, "end"),
    )
    print(f"\n== Call ended duplicate={ended.get('duplicate')} ==")

    time.sleep(1)
    watcher.stop()
    final = _poll_call(headers, call_short_id)
    print(f"\nFinal state: call_event={final.get('call_event')} turns={_transcript_len(final)}")
    print(f"SSE turns received: {watcher.seen_turns}")
    print(f"\nOpen in UI: {BASE_URL}/observability/calls/{call_short_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print(
            "\nSet credentials before running (no inline comments on export lines):\n"
            "  export EFFICIENTAI_API_KEY='paste-full-key-here'\n"
            "  export EFFICIENTAI_WORKSPACE_ID='your-workspace-uuid'\n"
            "\nYou are already in efficientAI/ if pwd shows that path — skip 'cd efficientAI'.\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
