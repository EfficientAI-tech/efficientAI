# Local Dev: Live Calls (V1)

Goal: validate STT/LLM/TTS live flow and trace naming locally before external webhook expansion.

## Prerequisites

- Docker + Docker Compose
- BYOK provider credentials for your voice bundle providers
- EfficientAI OTLP credentials:
  - `EFFICIENT_AI_API_KEY`
  - `EFFICIENT_AI_AGENT_ID` (or `EFFICIENT_AI_PROJECT_ID`)

## Core environment

Set:

- `OBSERVABILITY_ENABLED=true`
- `OBSERVABILITY_TRACING_ENABLED=true`
- `OBSERVABILITY_TRACING_EXPORTER=efficientai_http`
- `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-http.efficientai.ai/v1/traces`

Optional local debug:

- `OBSERVABILITY_TRACING_EXPORTER=console`

## Run path

1. Start local stack (`api`, `db`, `redis`, `frontend`) with compose.
2. Open playground / voice agent websocket flow.
3. Start one live call through `run_voice_bundle_fastapi`.
4. Confirm call end stores metadata in `CallRecording`.
5. Open call detail and verify trace fetch / waterfall rendering.

## Troubleshooting trace fetch

### Tempo is running but UI shows “Trace not found”

These are different problems:

| Check | Command / signal |
|-------|------------------|
| Tempo process up | `curl -sf http://localhost:3200/ready` → 200 |
| Spans actually stored | `curl "http://localhost:3200/api/search?limit=5"` → `traces` non-empty |
| Trace for this call | `curl "http://localhost:3200/api/traces/{trace_id}"` → 200 with batches |

A **`trace_id` on the call record only means the pipeline created a local OTel trace.** Spans must still be exported to Tempo during the call (`exporter: tempo_http`, endpoint `http://localhost:4318/v1/traces`) from the **media** process (`:8001` when using `start-all`).

Common causes of 404 on trace query:

- Tempo was **paused/stopped** during the call (export failed; ID still saved on call).
- Trace **expired** — default retention is **24h** (`observability/tempo/tempo.yml`).
- Tempo volume was **recreated** (empty store; old `trace_id` links remain in Postgres).
- API/media not using tracing config (`observability.tracing.enabled: false`).

After fixing export, run a **new** test call and verify the trace exists in Tempo before opening Observability.

### API returned 502 for traces (legacy)

Older builds mapped Tempo 404 → HTTP 502. Current API returns **404** with an explicit “not found in trace store” message when Tempo is reachable but empty.

## Validation checklist

- call emits `conversation -> turn -> stt/llm/tts`
- attributes map to span contract
- call has a persisted `trace_id`
- trace endpoint resolves the same `trace_id`
- summary endpoint reports call counts and durations
