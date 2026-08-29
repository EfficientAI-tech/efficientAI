# Custom SDK Observe Guide (Phase 2)

Use this when ingesting external calls while preserving trace linkage.

## Endpoint

POST `https://api.efficientai.ai/api/v1/observability/observe`

For incremental live runtime tracking (LiveKit/Pipecat/external):

POST `https://api.efficientai.ai/api/v1/observability/live/events`

Include auth:

- `x-efficient-ai-api-key`
- `x-efficient-ai-agent-id` (or project ID)

## Minimum payload

```json
{
  "id": "provider-call-id",
  "provider_platform": "retell",
  "startedAt": "2026-08-07T08:20:00Z",
  "endedAt": "2026-08-07T08:21:02Z",
  "messages": [{"role": "assistant", "content": "hello"}],
  "trace_id": "0af7651916cd43dd8448eb211c80319c"
}
```

## Mapping rules

- `id` -> provider call identifier
- `provider_platform` -> provider namespace
- `trace_id` -> call-to-trace join key
- `messages` -> transcript/evaluation input

Live event envelope fields are documented in `docs/telemetry/live-event-contract.md`.

## Validation checklist

- `trace_id` present for every completed call
- all timestamps in ISO-8601 UTC
- no credential or secret fields included in payload/body
