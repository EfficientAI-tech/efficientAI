---
id: observability
title: Observability
sidebar_position: 1
---

# Observability

## What is Observability?

**Observability** lets you track and monitor all calls made by your Voice AI in production.

Instead of only testing with simulated calls, you can connect your live Voice AI to EfficientAI and see real call data flowing in. This gives you visibility into:
- What calls are happening
- How your AI is performing in the real world
- Issues that occur in production

---

## How It Works

EfficientAI provides webhook endpoints that your Voice AI provider can send call events to:

```
POST /api/v1/observability/calls
```

When a call starts, ends, or has an event, your provider sends the data to EfficientAI, and we store and analyze it.

---

## Supported Providers

EfficientAI can ingest calls from any voice AI platform:

| Provider | Integration Type |
|----------|-----------------|
| **Retell** | Dedicated webhook (no API key needed) |
| **Vapi** | Generic webhook |
| **Custom** | Generic webhook |

---

## Setting Up Observability

### For Retell

Use the dedicated Retell webhook endpoint (no EfficientAI API key required):

```
POST https://your-domain.com/api/v1/observability/calls/retell/webhook
```

Configure this URL in your Retell dashboard under webhook settings.

### For Other Providers

Use the generic webhook endpoint with your API key:

```bash
curl -X POST https://your-domain.com/api/v1/observability/calls \
  -H "X-EFFICIENTAI-API-KEY: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_platform": "vapi",
    "provider_call_id": "call_abc123",
    "agent_id": "your-agent-uuid",
    "call_data": {
      "event": "call_ended",
      "duration": 120,
      "transcript": "..."
    }
  }'
```

---

## Viewing Call Data

Once calls are ingested, you can:

1. **List all calls**: `GET /api/v1/observability/calls`
2. **View call details**: `GET /api/v1/observability/calls/{call_short_id}`
3. **Delete a call**: `DELETE /api/v1/observability/calls/{call_short_id}`

All calls appear in the Observability dashboard in the frontend.

---

## Webhook Payload Format

The webhook accepts flexible payloads to support different providers:

```json
{
  "provider_platform": "retell",
  "provider_call_id": "call_123",
  "agent_id": "agent-uuid-or-external-id",
  "call_data": {
    "event": "call_ended",
    "duration": 120,
    "transcript": "Hello, how can I help you today?..."
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `provider_platform` | Yes | Name of the voice AI provider |
| `provider_call_id` | Yes | The call ID from the provider |
| `agent_id` | No | Links to your EfficientAI Agent |
| `call_data` | Yes | Full call payload from provider |
