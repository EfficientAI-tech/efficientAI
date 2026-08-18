# Retell Integration and Call Observability

This guide captures the Retell Level 1 integration flow:

1. Load provider agents into EfficientAI integration pickers.
2. Ingest Retell call payloads via webhook.
3. Reconcile incomplete webhook payloads with on-demand provider refresh.

## Required Retell scope

- API key with access to:
  - `agent.list` and `agent.retrieve`
  - `call.retrieve`

## Provider agent catalog

EfficientAI endpoint:

- `GET /api/v1/integrations/{integration_id}/external-agents`

For Retell integrations this normalizes provider agents to:

```json
{
  "agents": [
    { "id": "agent_...", "name": "Support Agent", "archived": false }
  ],
  "has_more": false,
  "next_cursor": null
}
```

## Webhook ingest

Retell webhook endpoint:

- `POST /api/v1/observability/calls/webhook/retell/{api_key}`

Expected native shape:

```json
{
  "event": "call_ended",
  "call": { "call_id": "...", "...": "..." }
}
```

Behavior:

- Terminal Retell events are normalized to `call_event=call_ended`
- If a terminal payload is incomplete (missing transcript/call analysis/call cost), EfficientAI performs one pull fallback via `call.retrieve` and upserts richer `call_data`

## Manual refresh endpoint

To force a provider re-pull from observability detail:

- `POST /api/v1/observability/calls/{call_short_id}/refresh`

This resolves the linked integration and refreshes `call_data` using the provider call ID.

## Level 1 dashboard expectations

Retell call detail should include:

- Call summary and sentiment (`call_analysis.*`)
- Cost and product costs (`call_cost.*`)
- Latency buckets (`latency.e2e/asr/llm/tts`)
- Transcript turns (`transcript_object` / transcript text)
- Recording links (`recording_url`, `recording_multi_channel_url`)
- Archived playback copies are stored in S3 as `call_data.recording_s3_key` when S3 is configured

Trace note:

- Level 1 uses provider call report payloads.
- Level 2 synthetic provider traces are available for Retell when `transcript_object` and/or `latency` are present in stored `call_data` (`trace_source=retell_synthetic`).
- Retell synthetic traces are persisted to `call_data.provider_trace` on terminal webhook ingest, sparse-enrich fallback, and manual refresh.
- `GET /calls/{call_short_id}/trace` serves stored provider traces first and only rebuilds when no persisted trace exists.
- Recording playback is served from S3 (`recording_s3_key`) after provider audio is archived on ingest, refresh, or first `/audio` request.
- Level 3 EfficientAI-native OTEL traces are separate scope.
