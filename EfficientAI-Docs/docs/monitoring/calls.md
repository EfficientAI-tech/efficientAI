---
id: calls
title: Calls
sidebar_position: 2
---

# Calls

## What are Calls?

**Calls** in EfficientAI represent real voice conversations happening in your production environment. By forwarding live call data to EfficientAI, you can inspect transcripts, review metadata, and run evaluations on real customer interactions — not just simulated tests.

This is useful when you want to:
- Monitor how your Voice AI handles real customers
- Evaluate production calls against your quality criteria
- Track call metadata like duration, phone numbers, and end reasons
- Compare real-world performance against your test scenarios

---

## Endpoint

```
POST /api/v1/observability/calls
```

**Authentication**: Requires your EfficientAI API key in the `X-EFFICIENTAI-API-KEY` header.

---

## JSON Payload Structure

Each request sends **one call** at a time. The payload is flat (not nested inside a `call_data` wrapper):

```json
{
  "id": "0199e72d-795e-7ffe-b9b9-d3b08a3a11ae",
  "agent_id": 2,
  "startedAt": "2025-10-15T09:22:21.787Z",
  "endedAt": "2025-10-15T09:24:30.229Z",
  "to_phone_number": "+18646190758",
  "from_phone_number": "+14155551234",
  "messages": [
    {
      "role": "bot",
      "content": "Hi there. This is Alex from Tech Solutions customer support. How can I help you today?",
      "start_time": 1760520142852,
      "end_time": 1760520147842
    },
    {
      "role": "user",
      "content": "Yeah. I have a question about a recent recurring charge on my account.",
      "start_time": 1760520149392,
      "end_time": 1760520153012
    }
  ],
  "metadata": {
    "customer_name": "John Doe",
    "call_type": "support"
  },
  "endedReason": "customer-hungup",
  "recording_url": "https://storage.example.com/recordings/call_123.wav",
  "provider_platform": "vapi"
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | String | **Yes** | Unique identifier for the call (used as `provider_call_id` internally) |
| `agent_id` | String or Integer | No | Links the call to an EfficientAI Agent. Can be a numeric external ID or a UUID. |
| `startedAt` | ISO 8601 String | No | When the call started (e.g., `"2025-10-15T09:22:21.787Z"`) |
| `endedAt` | ISO 8601 String | No | When the call ended |
| `to_phone_number` | String | No | The number that was called (E.164 format recommended) |
| `from_phone_number` | String | No | The number that initiated the call |
| `messages` | Array | No | Structured transcript of the conversation (see below) |
| `metadata` | Object | No | Arbitrary key-value pairs (customer name, call type, tags, etc.) |
| `endedReason` | String | No | Why the call ended (e.g., `"customer-hungup"`, `"assistant-ended-call"`, `"voicemail"`, `"error"`) |
| `recording_url` | String | No | URL to the call recording file (WAV, MP3, etc.) — used later for audio-based evaluations |
| `provider_platform` | String | No | Name of the voice AI platform (e.g., `"vapi"`, `"retell"`, `"custom"`). Defaults to `"external"`. |

:::tip Extra Fields
The endpoint accepts additional fields beyond those listed above. Any extra fields are automatically captured and stored in the call data, so you can forward your provider's full payload without stripping fields.
:::

### Message Object

Each item in the `messages` array represents a single utterance in the conversation:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | String | **Yes** | Who spoke — `"bot"` / `"assistant"` for the AI, `"user"` for the caller |
| `content` | String | **Yes** | The text of what was said |
| `start_time` | Number | No | Unix timestamp (milliseconds) when the utterance started |
| `end_time` | Number | No | Unix timestamp (milliseconds) when the utterance ended |

---

## Retell Webhook

Retell has a dedicated webhook endpoint that does **not** require an API key. Configure this URL in your Retell dashboard:

```
POST https://your-domain.com/api/v1/observability/calls/retell/webhook
```

Retell sends its native payload format directly — no transformation needed on your side.

---

## Vapi Webhook

For Vapi, use the generic call ingestion endpoint. You can forward Vapi's `server-url` call events or transform them into the flat format above:

```bash
curl -X POST https://your-domain.com/api/v1/observability/calls \
  -H "X-EFFICIENTAI-API-KEY: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "call_abc123",
    "agent_id": "your-agent-id",
    "startedAt": "2025-10-15T09:22:21.787Z",
    "endedAt": "2025-10-15T09:24:30.229Z",
    "messages": [...],
    "endedReason": "assistant-ended-call",
    "provider_platform": "vapi"
  }'
```

---

## Running Evaluations on Calls

Once a call is ingested, you can trigger an LLM evaluation on it directly from the UI or the API.

### From the UI

1. Navigate to **Calls** in the sidebar
2. Click on a call to open its detail page
3. Click **Run Evaluation**
4. Select an evaluator from the dropdown
5. The evaluation runs asynchronously — you'll be redirected to the results page

### From the API

```bash
curl -X POST https://your-domain.com/api/v1/observability/calls/{call_short_id}/evaluate \
  -H "X-EFFICIENTAI-API-KEY: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "evaluator_id": "your-evaluator-uuid"
  }'
```

The evaluation uses the call's `messages` to build a transcript and runs it through the selected evaluator's LLM criteria (Follow Instructions, Problem Resolution, Professionalism, etc.).

---

## Viewing Call Data

| Action | Endpoint |
|--------|----------|
| List all calls | `GET /api/v1/observability/calls` |
| View call details | `GET /api/v1/observability/calls/{call_short_id}` |
| Delete a call | `DELETE /api/v1/observability/calls/{call_short_id}` |

The Calls dashboard in the frontend shows all ingested calls with filtering by event type, provider badges, and relative timestamps.

---

## Local Development with ngrok

Since EfficientAI receives webhooks from external providers, your local server needs to be publicly reachable. [ngrok](https://ngrok.com/) creates a secure tunnel from the internet to your local machine.

### Step 1: Install ngrok

```bash
# macOS
brew install ngrok

# Linux (snap)
sudo snap install ngrok

# Or download from https://ngrok.com/download
# and unzip into your PATH
```

### Step 2: Create a free ngrok account

Sign up at [https://dashboard.ngrok.com/signup](https://dashboard.ngrok.com/signup) and copy your auth token.

```bash
ngrok config add-authtoken YOUR_AUTH_TOKEN
```

### Step 3: Start EfficientAI locally

Make sure EfficientAI is running on its default port:

```bash
# Using Docker
docker compose up -d

# Or using CLI
eai start
```

Verify the API is accessible at `http://localhost:8000/docs`.

### Step 4: Start the ngrok tunnel

Point ngrok at the port where EfficientAI is running (default `8000`). ngrok does not occupy this port — it creates a public URL that forwards traffic to your local server.

```bash
ngrok http 8000
```

If EfficientAI is running on a different port (e.g., you changed it in `config.yml`), use that port instead:

```bash
ngrok http 9000
```

You'll see output like:

```
Session Status    online
Forwarding        https://a1b2c3d4.ngrok-free.app -> http://localhost:8000
```

Copy the `https://....ngrok-free.app` URL — this is your public webhook URL.

:::info ngrok dashboard
ngrok also starts a local inspection dashboard at `http://localhost:4040` where you can see all incoming webhook requests, replay them, and inspect payloads — useful for debugging.
:::

### Step 5: Configure your Voice AI provider

Use the ngrok URL as your webhook endpoint:

**For Retell:**
```
https://a1b2c3d4.ngrok-free.app/api/v1/observability/calls/retell/webhook
```
Set this in the Retell dashboard under **Settings → Webhooks**.

**For Vapi:**
```
https://a1b2c3d4.ngrok-free.app/api/v1/observability/calls
```
Set this as your Vapi `server-url` and include the `X-EFFICIENTAI-API-KEY` header.

**For custom integrations:**
```
https://a1b2c3d4.ngrok-free.app/api/v1/observability/calls
```

### Step 6: Test with a real call

Make a call to your Voice AI agent. You should see the webhook hit in the ngrok terminal and the call appear in the EfficientAI Calls dashboard.

:::caution ngrok URL Changes
The free tier of ngrok generates a new URL each time you restart it. If you need a stable URL, consider ngrok's paid plan with custom domains, or use a tool like [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).
:::

---

## Testing with Postman

You can also send test call data manually using Postman or curl:

```bash
curl -X POST http://localhost:8000/api/v1/observability/calls \
  -H "X-EFFICIENTAI-API-KEY: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-call-001",
    "agent_id": 1,
    "startedAt": "2025-10-15T09:22:21.787Z",
    "endedAt": "2025-10-15T09:24:30.229Z",
    "to_phone_number": "+18646190758",
    "from_phone_number": "+14155551234",
    "messages": [
      {
        "role": "bot",
        "content": "Hi there. This is Riley from Wellness Partners. How can I help you today?",
        "start_time": 1760520142852,
        "end_time": 1760520147842
      },
      {
        "role": "user",
        "content": "Hi, I need to schedule a medical appointment.",
        "start_time": 1760520149392,
        "end_time": 1760520153012
      },
      {
        "role": "bot",
        "content": "Of course! I can help you with that. Could you tell me your preferred date and time?",
        "start_time": 1760520154442,
        "end_time": 1760520160522
      },
      {
        "role": "user",
        "content": "Next Tuesday morning would be great.",
        "start_time": 1760520161372,
        "end_time": 1760520164132
      }
    ],
    "metadata": {
      "customer_name": "Jane Smith",
      "call_type": "appointment_scheduling"
    },
    "endedReason": "assistant-ended-call",
    "recording_url": "https://storage.example.com/recordings/test-call-001.wav"
  }'
```

**Expected response** (HTTP 201):

```json
{
  "id": "uuid-of-call-recording",
  "call_short_id": "abc123",
  "provider_call_id": "test-call-001",
  "provider_platform": "external",
  "status": "processed",
  "message": "Call ingested successfully"
}
```

---

## Full Example: End-to-End Flow

Here's the complete workflow from ingesting a call to evaluating it:

1. **Ingest a call** → `POST /api/v1/observability/calls` with the call JSON
2. **View in dashboard** → Navigate to Calls in the sidebar, click the new call
3. **Inspect transcript** → Review the chat bubbles, metadata, phone numbers, and end reason
4. **Run evaluation** → Click "Run Evaluation", pick an evaluator, and submit
5. **View results** → You're redirected to the evaluation results page with LLM scores

This works identically for live production calls forwarded via webhook or test calls sent via Postman.
