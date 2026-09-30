# Twilio SMS chat eval

Messaging chat agents (`chat_connection_type=messaging_channels`, `messaging_channel=sms`) exercise production over **real SMS** in post-prod live eval.

## Flow

1. Eval registers a pending turn in Redis (pair: your Twilio **From** number and eval **recipient**).
2. EfficientAI sends the simulated customer message via Twilio REST (`Messages.json`).
3. Production replies by SMS to your Twilio number.
4. Twilio POSTs the inbound message to the **platform inbound webhook URL**.
5. The webhook routes by **To** number to the chat agent linked on that telephony inventory row, then completes the pending turn.

Fallback order if inbound does not arrive in time: `messaging_sync_reply_url`, then `outbound_webhook_url`.

## Setup

1. Add **Twilio** under Integrations → Telephony (Account SID + Auth Token).
2. Import or sync your SMS-capable numbers on **Telephony Numbers** (choose provider **and** which integration credential to fetch from if you have several).
3. Create a chat agent → **Messaging** → **SMS**. Select the **Twilio SMS number** (links credentials + From) and set **Eval recipient** (E.164).
4. Copy the **platform inbound webhook** from the agent form into Twilio Console → your number → **A message comes in** (HTTP POST). One URL for all agents; routing is by called number.
5. Set the public API base in **`config.yml`** (same pattern as Vobiz telephony URLs):

```yaml
twilio:
  webhook_base_url: "https://your-ngrok-subdomain.ngrok-free.dev"
```

Alternatively use `security.public_base_url` with the same https URL. Importing a Twilio number registers this SMS webhook on the number automatically when the base URL is configured.

For local dev, use ngrok to API port **8000** (see [Twilio SMS quickstart](https://www.twilio.com/docs/messaging/quickstart)).

### Twilio trial accounts

Free/trial Twilio accounts **cannot** send arbitrary SMS body text via the API ([error 572006](https://www.twilio.com/docs/errors/572006)). The `Body` field must be one of Twilio’s template **names** (same as Console “Try out SMS”), for example `sms_appointment_reminders`.

On the agent, set **Outbound SMS body (Twilio trial)** to one of those templates. EfficientAI sends that template to your eval recipient; you then **reply by SMS** to your Twilio number with the agent’s answer. The inbound webhook completes the eval turn.

Upgrade the Twilio account to send the simulated customer’s actual message text on each turn.

Use **Test send SMS** on the agent connection form (after saving) to run the same Twilio API call as eval outbound; credentials stay on the server.

## Webhook

`POST /api/v1/telephony/twilio/webhooks/sms-inbound`

Configure this URL on each Twilio SMS number. Requests are validated with `X-Twilio-Signature` using the Twilio integration tied to that number.

Legacy per-agent URLs (`/api/v1/chat/messaging/twilio/inbound/{token}`) still work for older agents that already have `twilio_inbound_webhook_token` in config.

## Sandbox push checklist

- [ ] `twilio.webhook_base_url` (or `security.public_base_url`) in deploy `config.yml` = public API HTTPS host (ngrok :8000 in dev)
- [ ] Twilio integration + number imported; agent links number + eval recipient (E.164 contact)
- [ ] `twilio_sms_trial_body_template` on agent until Twilio account is upgraded (paid)
- [ ] Twilio **upgraded** for bought-number → +91 SMS (trial returns 572003)
- [ ] Messaging geo permissions include recipient country
- [ ] Celery + Redis running for evals; reply SMS to Twilio number within ~90s per turn
- [ ] Agent form webhook copy matches Twilio Console (uses same base as import)

## Config keys

| Key | Description |
|-----|-------------|
| `messaging_channel` | `sms` |
| `messaging_recipient` | E.164 test recipient |
| Agent `telephony_phone_number_id` | Twilio line from Telephony Numbers (preferred) |
| `twilio_sms_trial_body_template` | Twilio trial template name (e.g. `sms_appointment_reminders`) |
| `messaging_telephony_integration_id` / inline SID+token | Legacy fallback only |
