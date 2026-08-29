# Provider Webhook Mapping (Phase 2)

## Supported endpoints

- `POST /api/v1/observability/calls/webhook/{api_key}` (flat payload)
- `POST /api/v1/observability/calls/webhook/retell/{api_key}`
- `POST /api/v1/observability/calls/webhook/elevenlabs/{api_key}`
- `POST /api/v1/observability/calls/webhook/vapi/{api_key}`

## Required normalized fields

- `provider_call_id`
- `provider_platform`
- `event`
- optional `trace_id`

## Retell

- accepts native shape: `{ "event": "...", "call": { ... } }`
- `call.call_id` or `call.id` maps to provider call ID
- terminal Retell events are normalized to `call_ended`
- if terminal payload is incomplete (missing transcript/analysis/cost), EfficientAI performs a one-shot provider pull refresh before returning

## ElevenLabs

- accepts provider payload, then normalizes platform to `elevenlabs`
- if payload is flat with `id`/`call_id`, route wraps to internal `call` shape
- supports OpenTelemetry webhook type `post_call_transcription_otel`:
  - expected shape: `{ "type": "post_call_transcription_otel", "data": { "conversation_id", "agent_id", "otlp_traces" } }`
  - persists `call_data.provider_trace` with:
    - `source` / `trace_source`
    - `trace_id`
    - `storage` (`inline` or `s3`)
    - `normalized_trace` (UI-ready trace payload)
    - optional `otlp_traces` (inline raw OTLP when small)
    - optional `trace_s3_key` (raw archive for large payloads)
  - stores trace source as `elevenlabs_post_call_webhook`
  - keeps provider span names (e.g. `elevenlabs.recv.user_transcript`) to avoid taxonomy collisions

### ElevenLabs webhook setup checklist

1. In ElevenLabs workspace settings, configure a post-call webhook URL:
   `POST /api/v1/observability/calls/webhook/elevenlabs/{api_key}`
2. Enable `events: ["transcript"]`.
3. Set transcript format to `opentelemetry`.
4. Ensure your ElevenLabs API key has `CONVAI_READ` scope for fallback GET trace fetches.

## Vapi

- accepts provider payload, then normalizes platform to `vapi`
- same fallback wrapping behavior as ElevenLabs path
- terminal statuses (`ended`, `completed`, `end-of-call-report`, `done`, `failed`) are normalized to `call_ended`
- if terminal payload is incomplete (missing transcript/analysis/cost sections), EfficientAI performs a one-shot provider pull refresh before returning

## Trace linking

Every provider payload should include:

- `trace_id` at top-level, or
- `trace_id` inside provider call payload

The backend persists `CallRecording.trace_id` when supplied.

For hosted providers, EfficientAI also persists provider traces in `call_data.provider_trace`
on terminal webhook ingest, refresh, or first trace fetch.

## Live runtime events (LiveKit / Pipecat / external)

- `POST /api/v1/observability/live/events` accepts the incremental envelope described in
  `docs/telemetry/live-event-contract.md`.
- Delivery is at-least-once, idempotent by `(organization_id, event_id)`.
- Events update `call_data` incrementally (no full overwrite) and keep existing provider data intact.
- Missing external `trace_id` values are backfilled by EfficientAI in the ingest ACK.
