# ElevenLabs Local ngrok Validation

This guide validates that ElevenLabs post-call webhooks reach local EfficientAI and create Observability rows.

## Scope

- Tunnel target: `http://localhost:8000` (API)
- Webhook route:
  `POST /api/v1/observability/calls/webhook/elevenlabs/{api_key}`
- Event type: `post_call_transcription_otel`
- Transcript format: `opentelemetry`

Do not use port `8001` for this path. Port `8001` is the telephony/media edge.

## Prerequisites

1. EfficientAI API stack running (venv path used by this repo):

```bash
source /Users/aadharsinghbhadauria/Desktop/efficientai/.venv/bin/activate
cd /Users/aadharsinghbhadauria/Desktop/efficientai/efficientAI
python -m app.cli start-all --config config.yml --no-reload --no-build-frontend
```

2. Active ElevenLabs integration in EfficientAI with `CONVAI_READ` scope.
3. At least one EfficientAI agent linked to an ElevenLabs provider agent (`voice_ai_agent_id`).

## Start ngrok

```bash
ngrok http 8000
```

Copy the generated HTTPS URL, for example:

`https://<id>.ngrok-free.app`

## Configure ElevenLabs webhook

In ElevenLabs workspace/agent webhook settings:

- URL:
  `https://<id>.ngrok-free.app/api/v1/observability/calls/webhook/elevenlabs/{api_key}`
- Events: `transcript`
- Transcript format: `opentelemetry`
- Avoid enabling audio webhook for migration validation (large base64 payload, not required for insights-only import).

## Run validation call

1. Start and finish a real call on the linked ElevenLabs agent.
2. Check ngrok request inspector:
   - Request path includes `/webhook/elevenlabs/{api_key}`
   - Response status is `201`
3. Open EfficientAI:
   - Observability -> Calls
   - Verify a new ElevenLabs row exists
   - Open call detail and verify transcript/insights

## Expected backend behavior

The webhook handler in `app/api/v1/routes/observability.py`:

- Accepts `post_call_transcription_otel` payload
- Resolves linked internal agent from provider `agent_id`
- Persists call shell + transcript
- Normalizes provider OTLP trace for the trace tab

## Troubleshooting

- `404 integration/agent`:
  Ensure the internal agent is linked to the ElevenLabs provider agent ID.
- `502 failed to list/fetch provider data`:
  Verify ElevenLabs key scope and integration key correctness.
- No row in Observability:
  Confirm route is on API `:8000` and the webhook URL includes the API key segment.
- No trace rendered:
  Confirm ElevenLabs sends `post_call_transcription_otel` and not plain JSON transcript.
