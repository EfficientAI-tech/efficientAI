# Telephony media workers and post-call processing

Live Vobiz calls use a **long-lived WebSocket** on the media router (`app/api/v1/media.py`), not a Celery task slot. Post-call work (ffmpeg merge, S3 upload, `CallRecording` persist, inbound evaluator dispatch) runs in the **`finalize_telephony_recording`** Celery task after the WebSocket handler enqueues it from `voice_bundle` / Gemini bot teardown.

## Deployment

| Process | Role |
|--------|------|
| **API replicas** | HTTP, webhooks, short requests |
| **Media workers** | Uvicorn (or similar) serving **only** `media_router` WebSockets — scale horizontally for concurrent calls |
| **Celery workers** | Outbound dial (`initiate_vobiz_outbound_call`), post-call finalize, evaluator scoring |

Set **`MEDIA_WS_BASE_URL`** (see `env.example`) so Vobiz answer XML points at the media host, e.g. `ws://media.internal:8001`. The API base URL can stay on general-purpose replicas; callers never need the media URL except via carrier XML.

## Recording artifacts

1. **Pipeline capture (default)** — Dual-track WAV from the STT/TTS (or Gemini) pipeline on the Vobiz media WebSocket: recorders use **stream timeline** (sequential frames, no wall-clock padding). Celery merges with lag detection + optional bot playback delay (`TELEPHONY_BOT_PLAYBACK_DELAY_MS`, default 400ms). If inbound audio already contains agent energy, merge uploads **inbound-only** to avoid double-counting. Otherwise tracks are delay-aligned and summed in Python (NumPy). Stored on `CallRecording.call_data.recording_s3_key` via `finalize_telephony_recording`.

2. **Carrier session recording (optional)** — Set `vobiz.carrier_session_recording: true` to add Vobiz `<Record>` on answer XML and ingest MP3 from `recording-ready` (allowlisted `vobiz.ai` hosts). When disabled, answer XML is stream-only and audio comes from Celery `finalize_telephony_recording` only.

Evaluators queue when transcript and/or `recording_s3_key` are present (`enqueue_linked_evaluator_result_if_ready`), typically after Celery finalize or carrier ingest — not from media disconnect alone (avoids racing pipeline finalize).

Inbound calls with an **active evaluator suite** inject the round-robin combination's persona and scenario into the voice agent system instruction via `build_system_instruction` (same path as outbound phone evals).

## Local dev

`docker-compose.yml` sets `MEDIA_WS_BASE_URL=ws://localhost:8001`. Run a media-capable process on that port (or leave unset to co-locate media WS on the main API for quick tests). Ensure Celery is running so post-call finalize is not left to the inline fallback.
