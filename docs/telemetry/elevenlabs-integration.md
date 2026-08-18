# ElevenLabs Integration and Trace Validation

This guide describes the ElevenLabs-first integration path for:

1. Loading provider agents into EfficientAI dropdowns.
2. Capturing ElevenLabs OTLP traces through webhook and on-demand APIs.
3. Validating end-to-end turn capture in observability.

## Required ElevenLabs scopes

- `CONVAI_READ` for:
  - `GET /v1/convai/agents`
  - `GET /v1/convai/conversations/{conversation_id}?format=opentelemetry`
- `CONVAI_WRITE` if creating signed web calls from EfficientAI.

## Provider agent catalog

EfficientAI backend endpoint:

- `GET /api/v1/integrations/{integration_id}/external-agents`

For ElevenLabs integrations, this proxies:

- `GET https://api.elevenlabs.io/v1/convai/agents`

and returns normalized rows:

```json
{
  "agents": [
    {
      "id": "agent_...",
      "name": "Customer Support Agent",
      "archived": false
    }
  ],
  "has_more": false,
  "next_cursor": null
}
```

## Trace ingestion surfaces

### 1) Post-call webhook (preferred durable path)

Webhook endpoint:

- `POST /api/v1/observability/calls/webhook/elevenlabs/{api_key}`

Expected OTLP webhook payload type:

- `post_call_transcription_otel`

EfficientAI stores:

- `call_data.provider_trace.source = elevenlabs_post_call_webhook`
- `call_data.provider_trace.trace_source = elevenlabs`
- `call_data.provider_trace.normalized_trace = { trace_id, root_span_id, spans }`
- `call_data.provider_trace.otlp_traces = { resourceSpans: ... }` (inline when small)
- `call_data.provider_trace.trace_s3_key` when raw OTLP exceeds inline threshold

### 2) On-demand fallback fetch

When opening call detail trace and no stored provider trace exists, EfficientAI can call:

- `GET /v1/convai/conversations/{conversation_id}?format=opentelemetry`

This path requires resolving the ElevenLabs integration linked to the call agent.
Fetched OTLP payloads are written back into `call_data.provider_trace` so subsequent loads do not require another provider API fetch.

## Span namespace rules

EfficientAI does not remap provider span names to internal names.

- Keep ElevenLabs names unchanged:
  - `elevenlabs.conversation`
  - `elevenlabs.recv.user_transcript`
  - `elevenlabs.recv.agent_response`
  - `elevenlabs.tool.*`
- Use `attributes.trace.provider = elevenlabs` on normalized spans.

This prevents collisions with EfficientAI-native names such as `turn`, `stt`, `llm`, and `tts`.

## End-to-end validation checklist

1. Save ElevenLabs integration in EfficientAI.
2. Confirm external agent dropdown populates from provider.
3. Link an EfficientAI agent to one ElevenLabs provider agent.
4. Configure ElevenLabs post-call webhook with transcript format `opentelemetry`.
5. Complete a test call with at least:
   - 2 user turns
   - 2 agent turns
6. Open observability call detail and verify trace view:
   - source badge shows `elevenlabs`
   - root span `elevenlabs.conversation`
   - user turn spans `elevenlabs.recv.user_transcript`
   - agent turn spans `elevenlabs.recv.agent_response`
   - tool spans nested under agent response (if tools are used)

## Regression fixtures

Keep redacted fixtures under:

- `tests/fixtures/elevenlabs/agents_list.json`
- `tests/fixtures/elevenlabs/conv.json`
- `tests/fixtures/elevenlabs/conv_otel.json`
- `tests/fixtures/elevenlabs/post_call_transcription_otel.json`

These fixtures back normalization and webhook tests.
