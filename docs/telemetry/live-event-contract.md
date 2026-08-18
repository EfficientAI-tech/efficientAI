# Live Event Contract (Incremental Ingest)

This document defines the platform-neutral envelope accepted by live observability ingest.

## Endpoint

- `POST /api/v1/observability/live/events`

## Envelope

```json
{
  "event_id": "evt_01J6H6FD4NBRS3P78N84TFM2QV",
  "call_id": "call_abc123",
  "event_type": "turn.assistant",
  "seq": 12,
  "event_ts": "2026-08-12T13:01:22.145Z",
  "platform": "livekit",
  "agent_ref": "agent_42",
  "payload": {
    "content": "Sure, I can help with that.",
    "latency": {
      "llm_ms": 420,
      "tts_ms": 210
    }
  },
  "trace_id": "0af7651916cd43dd8448eb211c80319c"
}
```

## Required fields

- `event_id`: globally unique idempotency key.
- `call_id`: provider/external call identifier.
- `event_type`: semantic event name (`call.started`, `turn.user`, `turn.assistant`, `call.ended`, etc).
- `seq`: monotonically increasing sequence per call.
- `event_ts`: event timestamp in ISO-8601 UTC.
- `platform`: source runtime/platform (`livekit`, `pipecat`, `external`).
- `payload`: event body with provider-specific details.

## Optional fields

- `agent_ref`: external agent identifier.
- `trace_id`: external trace id for direct Level 3 correlation.

## Delivery and ordering semantics

- Delivery is **at-least-once**.
- Idempotency key is `(organization_id, event_id)`.
- Duplicate events return success with `duplicate=true` and do not mutate state.
- Events with sequence older than watermark by more than
  `OBSERVABILITY_LIVE_EVENT_MAX_OUT_OF_ORDER_SEQ` are rejected as stale.
- Accepted timestamp drift window is controlled by
  `OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS`.
- If `trace_id` is missing, EfficientAI issues one in ACK so clients can reuse it.

## Merge semantics

- `call.started`: creates/upserts call shell and stamps start metadata.
- `turn.*`: appends live transcript turns and updates in-progress state.
- `call.ended` / `call.failed`: stamps terminal state and final metadata.
- Existing `call_data` keys are preserved; only live-observability fields are patched.
