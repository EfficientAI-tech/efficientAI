# Telephony media workers and post-call processing

Live Vobiz calls use a **long-lived WebSocket** on the media router (`app/api/v1/media.py`), not a Celery task slot. Post-call work (ffmpeg merge, S3 upload, `CallRecording` persist, inbound evaluator dispatch) runs in the **`finalize_telephony_recording`** Celery task after the WebSocket handler enqueues it from `voice_bundle` / Gemini bot teardown.

## Deployment

| Process | Role | Docker Compose service |
|--------|------|------------------------|
| **API** | HTTP CRUD, Vobiz webhooks (`SERVICE_MODE=api`) | `api` (:8000) |
| **Media** | Live voice WebSockets only (`SERVICE_MODE=media`) | `media` (:8001) |
| **Celery workers** | Outbound dial, post-call finalize, evaluator scoring | `worker`, `worker-imports` |

Set **`MEDIA_WS_BASE_URL`** (or `vobiz.media_ws_base_url` in config) so Vobiz answer XML points at a **publicly reachable** media host, e.g. `wss://media.example.com` or a second ngrok tunnel to `:8001`.

The API does **not** proxy WebSocket audio. It only embeds the media URL in answer XML. Resolution order: `MEDIA_WS_BASE_URL` → else reuse `webhook_base_url` (https→wss). When API and media share one port (`SERVICE_MODE=all`), a separate media URL is not required.

### Local dev

- **`docker compose up`** — runs `api`, `media`, `worker`, `worker-imports`.
- **`eai start-all`** — spawns telephony media server + Celery workers + API (`SERVICE_MODE=api` on the API process). Use `--no-telephony-worker` to skip media.
- **`eai start`** — API only (production/docker `api` service).

Override `MEDIA_WS_BASE_URL` when media is on a different public host than webhooks.

## Capacity

One listen port accepts **many concurrent WebSocket connections** (one per live call). Scale media horizontally behind a WebSocket-capable load balancer; point `MEDIA_WS_BASE_URL` at the LB.

## Recording artifacts

1. **Pipeline capture (default)** — Dual-track WAV from the STT/TTS (or Gemini) pipeline on the Vobiz media WebSocket: recorders use **stream timeline** (sequential frames, no wall-clock padding). Celery merges with lag detection + optional bot playback delay (`TELEPHONY_BOT_PLAYBACK_DELAY_MS`, default 400ms). If inbound audio already contains agent energy, merge uploads **inbound-only** to avoid double-counting. Otherwise tracks are delay-aligned and summed in Python (NumPy). Stored on `CallRecording.call_data.recording_s3_key` via `finalize_telephony_recording`.

2. **Carrier session recording (optional)** — Set `vobiz.carrier_session_recording: true` to add Vobiz `<Record>` on answer XML and ingest MP3 from `recording-ready` (allowlisted `vobiz.ai` hosts). When disabled, answer XML is stream-only and audio comes from Celery `finalize_telephony_recording` only.

Evaluators queue when transcript and/or `recording_s3_key` are present (`enqueue_linked_evaluator_result_if_ready`), typically after Celery finalize or carrier ingest — not from media disconnect alone (avoids racing pipeline finalize).

Inbound calls with an **active evaluator suite** inject the round-robin combination's persona and scenario into the voice agent system instruction via `build_system_instruction` (same path as outbound phone evals).

## Live call storage

Live `call_recordings` and `evaluator_results` use the **catalog database** by default. When `database.sharding.enabled` is true, heavy payload columns are dual-written to shard tables (`evaluator_result_payloads`, `call_recording_payloads`). See [live-call-storage.md](./live-call-storage.md).
