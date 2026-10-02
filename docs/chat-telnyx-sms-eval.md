# Telnyx SMS chat eval

Messaging chat agents (`chat_connection_type=messaging_channels`, `messaging_channel=sms`) can use **Telnyx** for post-prod live SMS eval (same turn-wait model as Twilio).

## Flow

1. Eval registers a pending turn in Redis (pair: your Telnyx **From** number and eval **recipient**).
2. EfficientAI sends the simulated customer message via Telnyx `/v2/messages`.
3. Production replies by SMS to your Telnyx number.
4. Telnyx POSTs `message.received` to the **platform inbound webhook URL**.
5. The webhook routes by **to** number to the chat agent linked on that telephony inventory row, then completes the pending turn.

Fallback order if inbound does not arrive in time: `messaging_sync_reply_url`, then `outbound_webhook_url`.

## Setup

1. Add **Telnyx** under Integrations → Telephony (API Key, optional Messaging Profile ID on `voice_app_id`, Webhook Public Key on `verify_app_uuid`).
2. Import SMS-capable numbers on **Telephony Numbers** (provider **Telnyx**).
3. Point your **messaging profile** webhook to the platform SMS URL (profile-level — one URL for all numbers on that profile).
4. Create a chat agent → **Messaging** → **SMS**. Select the **Telnyx** number and set **Eval recipient** (E.164) when running evals.
5. Set the public API base in **`config.yml`**:

```yaml
telnyx:
  webhook_base_url: "https://your-ngrok-subdomain.ngrok-free.dev"
```

Import may PATCH the messaging profile webhook when `voice_app_id` (messaging profile id) is set on the integration.

## Webhook

`POST /api/v1/telephony/telnyx/webhooks/sms-inbound`

Verify requests with Telnyx Ed25519 headers (`telnyx-signature-ed25519`, `telnyx-timestamp`) using the integration **Webhook Public Key**.

Use **Test send SMS** via `POST /api/v1/agents/{id}/chat-messaging/test-telnyx-sms` after saving the agent.

## Voice (Call Control)

Inbound PSTN voice uses `POST /api/v1/telephony/telnyx/webhooks/voice`. Configure your Telnyx **Call Control Application** webhook to that URL. On `call.initiated`, the platform answers and starts media streaming to the existing carrier WebSocket voice agent pipeline.
