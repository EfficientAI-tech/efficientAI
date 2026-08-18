# Vapi Integration and Call Observability

This document describes the Vapi Level 1 integration path for:

1. Loading provider agents into EfficientAI dropdowns.
2. Capturing Vapi call payloads through webhook and on-demand refresh.
3. Validating call metrics, transcript, and dashboard coverage in observability.

## Required Vapi keys

- Private API key:
  - Server-side call metrics retrieval (`GET /call/{id}`)
  - Assistant listing (`GET /assistant`)
- Public key:
  - Required by Vapi web-call creation (`POST /call/web`)

## Provider agent catalog

EfficientAI backend endpoint:

- `GET /api/v1/integrations/{integration_id}/external-agents`

For Vapi integrations, this proxies:

- `GET https://api.vapi.ai/assistant`

and returns normalized rows:

```json
{
  "agents": [
    {
      "id": "assist_...",
      "name": "Support Assistant",
      "archived": false
    }
  ],
  "has_more": false,
  "next_cursor": null
}
```

## Webhook ingest

Vapi webhook endpoint:

- `POST /api/v1/observability/calls/webhook/vapi/{api_key}`

Expected behavior:

- Ingest provider payload and normalize platform to `vapi`
- For terminal events (`ended`, `completed`, `end-of-call-report`, `done`, `failed`), normalize `call_event` to `call_ended`
- If terminal payload is incomplete (missing transcript/analysis/cost sections), EfficientAI performs one provider pull fallback (`GET /call/{id}`) and upserts the richer payload

Recommended Vapi dashboard setup:

1. Configure your server URL to the endpoint above.
2. Ensure end-of-call payloads are enabled.
3. Keep provider call IDs and assistant IDs included in webhook payloads.

## Manual refresh endpoint

When webhook payloads are delayed or partial, use:

- `POST /api/v1/observability/calls/{call_short_id}/refresh`

Refresh flow:

1. Resolve call recording and linked internal agent.
2. Resolve voice integration and decrypt private key.
3. Pull latest provider payload from Vapi (`GET /call/{provider_call_id}`).
4. Overwrite `call_data` with the refreshed provider payload.

## What should appear in call detail (Level 1)

From the Vapi provider payload:

- Summary and success evaluation (`analysis.*`)
- Cost and token usage (`cost`, `costBreakdown.*`)
- Latency and interruption metrics (`analysis.latencyStats`, `artifact.performanceMetrics`)
- Transcript turns (`messages`, `artifact.messages`, fallback transcript text)
- Recording references (`recordingUrl`, `stereoRecordingUrl`, artifact recording URLs)

Trace note:

- Level 1 focuses on provider call reports.
- Level 2 synthetic traces (`trace_source=vapi_synthetic`) are persisted on webhook terminal ingest, sparse enrich fallback, and manual refresh.
- Trace stats include endpointing where Vapi exposes it (`metric.layer=endpointing`).
- Stored provider traces are served first; rebuilds happen only when persisted traces are missing.
- EfficientAI-native OTEL traces remain Level 3 scope.
