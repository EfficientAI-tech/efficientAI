# Call Traces — Pipecat integration

Connect your **Pipecat voice agent on your computer** to EfficientAI. Traces appear in **Observability → Calls** (`/observability/calls`).

You **do not** need to install or run EfficientAI locally for staging — only update your Pipecat project.

**In the UI:** open **Calls → Connect Pipecat** for a copy-paste setup with your workspace ID pre-filled.

---

## Part 1 — EfficientAI (browser)

1. Log in (e.g. https://staging.efficientai.cloud)
2. Select the correct **workspace**
3. **Settings → API keys** → create a key → copy it

---

## Part 2 — Pipecat project (your computer)

Create `.env` in your Pipecat folder (where you run `bot.py`):

```env
EFFICIENTAI_API_BASE=https://staging.efficientai.cloud
EFFICIENTAI_WORKSPACE_ID=<from Connect Pipecat tab>
EFFICIENTAI_API_KEY=<from Settings → API keys>

# Your voice provider keys
DEEPGRAM_API_KEY=...
OPENAI_API_KEY=...
CARTESIA_API_KEY=...
```

Do **not** set `EFFICIENTAI_CALL_SHORT_ID` — a new Call ID is created per call.

Install once:

```bash
pip install "pipecat-ai[silero,deepgram,openai,cartesia,runner,webrtc]>=1.4.0"
pip install "efficientai[otel] @ git+https://github.com/EfficientAI-tech/efficientAI.git"
```

---

## Part 3 — Three hooks in bot.py

**Imports (top of file):**

```python
from dotenv import load_dotenv
from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    require_deployment_trace_env,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
)
load_dotenv(override=True)
require_deployment_trace_env()
```

**When a call starts / ends (inside `run_bot`):**

```python
trace_ctx = await ensure_trace_session(
    transport=resolve_trace_transport(runner_args, transport),
)
tracing = setup_pipecat_worker_tracing(trace_ctx)

worker = PipelineWorker(
    pipeline,
    enable_tracing=True,
    additional_span_attributes=tracing["additional_span_attributes"],
)

@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    await worker.cancel()
    await close_trace_session(trace_ctx)
```

Full example: `docs/examples/pipecat_multi_provider_webrtc_tracing.py`

---

## Part 4 — Run and verify

```bash
uv run bot.py
```

Open **http://localhost:7860/client** → WebRTC → Connect → speak → Disconnect.

In EfficientAI: **Calls** tab → **Refresh** → open your Call ID row.

---

## What each piece does

| Piece | Role |
|-------|------|
| `.env` | API key, workspace, API base URL |
| `ensure_trace_session()` | Opens trace, gets six-digit Call ID |
| `setup_pipecat_worker_tracing()` | Sends spans to EfficientAI |
| `enable_tracing=True` | Pipecat records STT / LLM / TTS spans |
| `close_trace_session()` | Flushes spans and closes trace |

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Bot crashes on start | `EFFICIENTAI_API_KEY` and `EFFICIENTAI_WORKSPACE_ID` in `.env` |
| UI empty after call | `EFFICIENTAI_API_BASE` matches your environment |
| Call ID but empty trace | `enable_tracing=True` + `efficientai[otel]` installed |
| Trace stays open | `close_trace_session()` on disconnect |

---

## Other transports

WebSocket and phone use the same API. See `docs/examples/pipecat_inbound_phone_tracing.py`.

Local EfficientAI: set `EFFICIENTAI_API_BASE=http://localhost:8000` and run `eai start-all`.
