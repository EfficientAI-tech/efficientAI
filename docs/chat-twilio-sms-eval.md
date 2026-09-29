# Twilio SMS chat eval

Messaging chat agents (`chat_connection_type=messaging_channels`, `messaging_channel=sms`) exercise production over **real SMS** in post-prod live eval.

## Flow

1. Eval registers a pending turn in Redis (pair: your Twilio **From** number and eval **recipient**).
2. EfficientAI sends the simulated customer message via Twilio REST (`Messages.json`).
3. Production replies by SMS to your Twilio number.
4. Twilio POSTs the inbound message to your **inbound webhook URL**.
5. The webhook completes the pending turn; the eval worker receives the reply body.

Fallback order if inbound does not arrive in time: `messaging_sync_reply_url`, then `outbound_webhook_url`.

## Setup

1. Add **Twilio** under Integrations → Telephony (Account SID + Auth Token), or enter credentials on the agent.
2. Create a chat agent → **Messaging** → **SMS**. Set **From** (Twilio number) and **Eval recipient** (E.164).
3. Save the agent and copy the **Twilio inbound webhook** URL into Twilio Console → your number → **A message comes in** (HTTP POST).
4. Use a **public HTTPS** base URL (`PUBLIC_BASE_URL` / `FRONTEND_BASE_URL`). For local dev, use ngrok (see [Twilio SMS quickstart](https://www.twilio.com/docs/messaging/quickstart)).

## Webhook

`POST /api/v1/chat/messaging/twilio/inbound/{twilio_inbound_webhook_token}`

Token is generated automatically in `chat_connection_config` when the agent is saved. Requests are validated with `X-Twilio-Signature`.

## Config keys

| Key | Description |
|-----|-------------|
| `messaging_channel` | `sms` |
| `messaging_recipient` | E.164 test recipient |
| `twilio_from` | Twilio sender number |
| `messaging_telephony_integration_id` | Saved Twilio telephony row (preferred) |
| `twilio_account_sid` / `twilio_auth_token` | Inline fallback credentials |
| `twilio_inbound_webhook_token` | Auto-generated webhook path token |
