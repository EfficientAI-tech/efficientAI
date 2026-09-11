"""
Dev WebSocket bot for local EfficientAI + Pipecat trace testing.

Speaks the same generic JSON audio protocol as Agent Playground Custom WebSocket.
Exports sample STT/LLM/TTS spans per detected user turn (audio activity).

Usage:
  export EFFICIENTAI_API_KEY="<workspace api key>"
  uv run python scripts/pipecat_trace_dev_bot.py

Then Agent Playground → Custom WebSocket → ws://localhost:9001 → Connect.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

import httpx
import websockets

sys.stdout.reconfigure(line_buffering=True)

PORT = 9001
ECHO_DELAY_S = 2.0
GREETING_DELAY_S = 1.5
# ~100ms frames from playground generic protocol → 80 frames ≈ 8s of speech
FRAMES_PER_TURN = 80
GREETING_TEXT = (
    "Dev trace bot ready. Speak a few times — each speech burst exports one trace turn."
)


def _parse_trace_handshake(message: dict) -> dict | None:
    if message.get("type") == "efficientai_trace_handshake" and message.get("call_short_id"):
        return {
            "call_short_id": str(message["call_short_id"]),
            "agent_id": message.get("agent_id"),
            "workspace_id": message.get("workspace_id"),
            "otel_correlation": dict(message.get("otel_correlation") or {}),
        }
    legacy = message.get("efficientai_call_short_id")
    if legacy:
        return {
            "call_short_id": str(legacy),
            "agent_id": message.get("agent_id"),
            "workspace_id": message.get("workspace_id"),
            "otel_correlation": dict(message.get("otel_correlation") or {}),
        }
    return None


async def _post_turn_spans(handshake: dict, turn_number: int) -> None:
    api_key = os.environ.get("EFFICIENTAI_API_KEY", "").strip()
    if not api_key:
        print("    [trace] EFFICIENTAI_API_KEY not set — skipping span export")
        return

    otel = handshake.get("otel_correlation") or {}
    endpoint = otel.get("otlp_endpoint") or os.environ.get(
        "EFFICIENTAI_OTLP_ENDPOINT",
        "http://localhost:8000/api/v1/observability/traces",
    )
    call_short_id = handshake["call_short_id"]
    agent_id = handshake.get("agent_id")
    workspace_id = handshake.get("workspace_id")

    trace_id = f"dev{call_short_id}"
    base_ttfb = 0.1 + (turn_number % 3) * 0.05
    spans = []
    for name, op, mult in [("stt", "stt", 1.0), ("llm", "chat", 2.5), ("tts", "tts", 1.4)]:
        spans.append(
            {
                "traceId": trace_id,
                "spanId": f"{name}-t{turn_number}-{uuid.uuid4().hex[:6]}",
                "name": name,
                "attributes": [
                    {"key": "gen_ai.operation.name", "value": {"stringValue": op}},
                    {"key": "turn.number", "value": {"intValue": str(turn_number)}},
                    {"key": "metrics.ttfb", "value": {"doubleValue": round(base_ttfb * mult, 3)}},
                    {"key": "efficientai.call_short_id", "value": {"stringValue": call_short_id}},
                ],
            }
        )
        if agent_id:
            spans[-1]["attributes"].append(
                {"key": "efficientai.agent_id", "value": {"stringValue": str(agent_id)}}
            )
        if workspace_id:
            spans[-1]["attributes"].append(
                {"key": "efficientai.workspace_id", "value": {"stringValue": str(workspace_id)}}
            )

    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "X-EfficientAI-Call-Short-Id": call_short_id,
    }
    if agent_id:
        headers["X-EfficientAI-Agent-Id"] = str(agent_id)
    if workspace_id:
        headers["X-Workspace-Id"] = str(workspace_id)

    payload = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()
        print(
            f"    [trace] Turn {turn_number}: exported 3 spans "
            f"(stt/llm/tts ~{int(base_ttfb*1000)}/{int(base_ttfb*mult*2500)}/{int(base_ttfb*1400)}ms) "
            f"correlated={body.get('correlated')}"
        )


async def _close_trace_session(handshake: dict) -> None:
    api_key = os.environ.get("EFFICIENTAI_API_KEY", "").strip()
    workspace_id = handshake.get("workspace_id")
    call_short_id = handshake.get("call_short_id")
    if not api_key or not workspace_id or not call_short_id:
        return
    base = os.environ.get("EFFICIENTAI_API_BASE", "http://localhost:8000").rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as client:
        await client.post(
            f"{base}/api/v1/observability/traces/sessions/{call_short_id}/close",
            headers={"X-API-Key": api_key, "X-Workspace-Id": str(workspace_id)},
        )
        print(f"    [trace] Closed session {call_short_id}")


async def echo_worker(queue: asyncio.Queue, ws):
    while True:
        frame_b64, scheduled_time = await queue.get()
        wait = scheduled_time - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await ws.send(json.dumps({"audio": frame_b64}))
        except websockets.exceptions.ConnectionClosed:
            break


async def handler(ws):
    remote = ws.remote_address
    print(f"[+] Client connected from {remote}")

    echo_queue: asyncio.Queue = asyncio.Queue()
    worker_task = asyncio.create_task(echo_worker(echo_queue, ws))
    audio_count = 0
    turn_number = 0
    last_export_at_frames = 0
    start = time.time()
    greeting_sent = False
    handshake: dict | None = None

    try:
        async for raw in ws:
            if not greeting_sent and time.time() - start > GREETING_DELAY_S:
                greeting_sent = True
                await ws.send(
                    json.dumps({"type": "transcript", "role": "agent", "content": GREETING_TEXT})
                )

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            if handshake is None:
                parsed = _parse_trace_handshake(msg)
                if parsed:
                    handshake = parsed
                    print(f"    [trace] Handshake call_short_id={handshake['call_short_id']}")
                    continue

            audio_b64 = msg.get("audio")
            if audio_b64 and isinstance(audio_b64, str) and len(audio_b64) > 20:
                audio_count += 1
                echo_queue.put_nowait((audio_b64, time.time() + ECHO_DELAY_S))

                if handshake and audio_count - last_export_at_frames >= FRAMES_PER_TURN:
                    turn_number += 1
                    last_export_at_frames = audio_count
                    await _post_turn_spans(handshake, turn_number)
    finally:
        worker_task.cancel()
        if handshake and audio_count > last_export_at_frames:
            turn_number += 1
            await _post_turn_spans(handshake, turn_number)
        if handshake:
            await _close_trace_session(handshake)
        print(f"[-] Session ended — {audio_count} audio frames, {turn_number} trace turns exported")


async def main():
    print(f"Pipecat trace dev bot on ws://localhost:{PORT}")
    print("Set EFFICIENTAI_API_KEY once, then connect from Agent Playground Custom WebSocket.")
    async with websockets.serve(handler, "0.0.0.0", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
