# Telemetry Docs (Product Observability)

This folder defines the Product Observability contract for EfficientAI live calls.
It is the source of truth for:

- what we trace
- which span names and attributes are stable
- PII and data-handling boundaries
- local developer setup for validating live STT/LLM/TTS traces
- scale architecture for high-volume traffic

## Documents

- `taxonomy.md`: Product observability vs platform observability ownership.
- `span-contract.md`: Required span names and attributes for EfficientAI UI.
- `pii-policy.md`: Transcript and sensitive data policy for trace attributes.
- `local-dev-live-calls.md`: Local V1 flow and environment setup.
- `scale-architecture.md`: Media plane, collector, sampling, and quotas.
- `live-event-contract.md`: Platform-neutral live event envelope and ingest semantics.

## V1 scope guardrails

V1 focuses on live calls first:

- In scope: `conversation`, `turn`, `stt`, `llm`, `tts`, `trace_id` linking.
- Out of scope: `s2s`, `tool_call`, external provider webhooks, platform ops.

Phase 2 extends to external webhooks and additional span types.

## Implementation status

- [x] Live tracing bootstrap (`efficientai_otel`) and `trace_id` call linkage
- [x] Trace waterfall UI and trace fetch API (`cloud` + `tempo`)
- [x] Calls summary cards with latency/volume and trace/eval rates
- [x] Header-auth observe endpoint (`POST /api/v1/observability/observe`)
- [x] Webhook ingest routes for flat, Retell, ElevenLabs, and Vapi payloads
- [x] Optional transcript attribute suppression via `OBSERVABILITY_TRACING_INCLUDE_TRANSCRIPTS`
- [x] Agent-level auto-eval trigger on `call_ended` webhook ingest
- [x] `tool_call`/`s2s` span naming alignment and TraceTree colors
- [x] Quota/sampling config hooks for scale preparation docs
- [x] Provider trace persistence (`call_data.provider_trace`) with stored-first trace resolution
- [x] S3 trace archival fallback for large provider trace payloads (`provider_trace.trace_s3_key`)
- [x] Live event contract and rollout flags for staged live-call tracking
- [x] Idempotent incremental live event ingest (`POST /api/v1/observability/live/events`)
- [x] Rolling live latency percentile APIs (`GET /api/v1/observability/live/metrics/latency`)
- [x] Agent-scoped live latency percentile API (`GET /api/v1/observability/live/agents/{agent_id}/latency`)
- [x] Level 3 trace-correlation fallback (ingest ACK issues trace id when external trace id is missing)
- [x] Live SLO breach recording + evaluator automation hooks (flag-gated)
