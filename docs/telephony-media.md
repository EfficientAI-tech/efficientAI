# Telephony media workers and post-call processing

Live Vobiz calls use a **long-lived WebSocket** on the telephony/media router (`app/api/v1/media.py`), not a Celery task slot. Post-call work (ffmpeg merge, S3 upload, `CallRecording` persist, inbound evaluator dispatch) runs in the **`finalize_telephony_recording`** Celery task after the WebSocket handler enqueues it from `voice_bundle` / Gemini bot teardown.

## Deployment (telephony edge)

| Process | Role | Docker Compose service |
|--------|------|------------------------|
| **API** | HTTP CRUD, UI, authenticated Vobiz admin (`numbers/*`, `calls/outbound`) | `api` (:8000) |
| **Telephony (media)** | **Carrier-facing edge**: Vobiz webhooks + live WebSockets | `media` (:8001) |
| **Celery workers** | Outbound dial, post-call finalize, evaluator scoring | `worker`, `worker-imports` |

Vobiz sees **one public host** (the telephony edge):

- `POST/GET /api/v1/telephony/vobiz/webhooks/answer`
- `POST /api/v1/telephony/vobiz/webhooks/events`
- `POST /api/v1/telephony/vobiz/webhooks/recording-ready`
- `WSS /api/v1/telephony/carrier/ws` (shared live-audio socket for Plivo, Vobiz, and other Stream-compatible carriers)

Configure **`vobiz.webhook_base_url`** to that public URL (e.g. `https://telephony.staging.example.com`). When `media_ws_base_url` / `MEDIA_WS_BASE_URL` is unset, carrier answer XML reuses the same host (`https` → `wss`) via `carrier_media_ws_base_url()`.

The product API does **not** proxy WebSocket audio and does **not** expose Vobiz carrier webhooks in split mode.

### Browser voice-agent (Agents “Talk”)

When API and telephony run on different ports, browser web calls still use API `/voice-agent/connect` and may need optional **`media_ws_base_url`** / `MEDIA_WS_BASE_URL` pointing at telephony for the returned `ws_url`. Vobiz PSTN does not need a separate media URL when `webhook_base_url` already targets telephony.

### Local dev

- **`docker compose up`** — runs `api`, `media`, `worker`, `worker-imports`.
- **`eai start-all`** — spawns telephony worker + Celery + API.
- **`eai start`** — single process; webhooks and WebSockets co-locate on `:8000` when `MEDIA_WS_BASE_URL` is unset.

#### Local Vobiz inbound test (split, staging-like)

1. Start stack: `eai start-all` or `docker compose up api media worker`.
2. Start Celery worker if not already running.
3. **One ngrok tunnel to telephony**: `ngrok http 8001`
4. In `config.yml`:

   ```yaml
   vobiz:
     webhook_base_url: "https://<your-tunnel>.ngrok-free.dev"
     webhook_verify: false   # local dev only
   ```

   Do **not** set `media_ws_base_url` for Vobiz (same host is used for WS).

5. **Re-import** the phone number or update the Vobiz application answer URL so it points at the telephony tunnel (not `:8000`).
6. Place an inbound call; confirm telephony logs show both **answer webhook** and **WebSocket accepted**.

Optional: set `media_ws_base_url: "ws://localhost:8001"` (or ngrok wss URL) if testing **browser** voice-agent with split services.

## Hard cutover checklist

Use when moving from API-hosted webhooks to telephony edge:

1. Deploy telephony/media with Vobiz `webhook_router` mounted.
2. Set `vobiz.webhook_base_url` to the **telephony public URL** in all environments.
3. Remove stale `MEDIA_WS_BASE_URL` from the API service env (optional; only needed for browser WS when split).
4. **Re-register Vobiz answer URLs** — import numbers again or update applications in the Vobiz dashboard (stored URLs may still reference the old API host).
5. Verify inbound call: telephony logs show `/webhooks/answer` and `/ws`; API logs do **not** show carrier webhooks.
6. Verify outbound call: API `POST /calls/outbound` still works; callbacks hit telephony host.
7. Enable `webhook_verify: true` in staging/prod after tunnel/LB URL is stable.

## Capacity

One listen port accepts **many concurrent WebSocket connections** (one per live call). Scale telephony horizontally behind a WebSocket-capable load balancer; point `webhook_base_url` at the LB (webhooks and WS share the same host).

## Recording artifacts

1. **Pipeline capture (default)** — Dual-track WAV from the STT/TTS (or Gemini) pipeline on the Vobiz media WebSocket: recorders use **stream timeline** (sequential frames, no wall-clock padding). Celery merges with lag detection + optional bot playback delay (`TELEPHONY_BOT_PLAYBACK_DELAY_MS`, default 400ms). If inbound audio already contains agent energy, merge uploads **inbound-only** to avoid double-counting. Otherwise tracks are delay-aligned and summed in Python (NumPy). Stored on `CallRecording.call_data.recording_s3_key` via `finalize_telephony_recording`.

2. **Carrier session recording (optional)** — Set `vobiz.carrier_session_recording: true` to add Vobiz `<Record>` on answer XML and ingest MP3 from `recording-ready` (allowlisted `vobiz.ai` hosts). When disabled, answer XML is stream-only and audio comes from Celery `finalize_telephony_recording` only.

Evaluators queue when transcript and/or `recording_s3_key` are present (`enqueue_linked_evaluator_result_if_ready`), typically after Celery finalize or carrier ingest — not from media disconnect alone (avoids racing pipeline finalize).

Inbound calls with an **active evaluator suite** inject the round-robin combination's persona and scenario into the voice agent system instruction via `build_system_instruction` (same path as outbound phone evals).

## Live call storage

Live `call_recordings` and `evaluator_results` use the **catalog database** by default. When `database.sharding.enabled` is true, heavy payload columns are dual-written to shard tables (`evaluator_result_payloads`, `call_recording_payloads`). See [live-call-storage.md](./live-call-storage.md).
