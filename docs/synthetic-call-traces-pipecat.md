# Call Traces — Pipecat integration

EfficientAI shows **per-turn STT, LLM, and TTS timing** from your Pipecat voice agent. Traces appear in **Call Traces** in the UI (`/call-traces`).

Primary dev path: **local WebRTC** via the Pipecat runner (`http://localhost:7860/client`).

---

## Environments

| Environment | `EFFICIENTAI_API_BASE` | UI |
|-------------|------------------------|-----|
| **Local** | `http://localhost:8000` | `http://localhost:5173` (or your Vite port) |
| **Staging** | `https://staging.efficientai.cloud` | `https://staging.efficientai.cloud` |

Set `EFFICIENTAI_API_BASE` once in `.env` or your deployment secret. Same `bot.py` for local and staging — only the base URL changes.

```bash
# Local bot → local API
EFFICIENTAI_API_BASE=http://localhost:8000

# Local bot → staging API (team testing)
EFFICIENTAI_API_BASE=https://staging.efficientai.cloud
```

OTLP export URL defaults to `{EFFICIENTAI_API_BASE}/api/v1/observability/traces`.

Use a **separate workspace** for local vs staging so traces do not mix in the UI.

---

## How it works

```
1. Pipecat bot starts a call → EfficientAI mints a 6-digit Call ID (call_short_id)
2. Pipecat emits STT / LLM / TTS spans (enable_tracing=True)
3. SDK exports spans → POST /api/v1/observability/traces
4. Call Traces UI shows latency + models per turn
5. Bot calls close_trace_session() → trace marked closed
```

Each call is linked by **`call_short_id`** (shown as `#482931` in the UI). Concurrent calls each get their own ID — ingest routes spans by `call_short_id` + `workspace_id`.

---

## Pipecat integration (v1)

We do **not** ship a single `PipecatTracer` wrapper class today. Integration is **three SDK functions** plus Pipecat's built-in tracing (`enable_tracing=True`).

> **v2 (optional later):** We may add a thin one-import wrapper (session + OTLP + cleanup). v1 stays explicit on purpose. The OTLP wire format will not change.

### Install

```bash
cd your-pipecat-project

uv pip install "pipecat-ai[silero,elevenlabs,fireworks,runner,webrtc]>=1.4.0"
# add STT/LLM/TTS extras for your stack
uv pip install -e '/path/to/efficientAI[otel]'
```

### Required env (set once per deployment)

```bash
EFFICIENTAI_API_KEY=<from EfficientAI → API keys>
EFFICIENTAI_WORKSPACE_ID=<workspace uuid>

# Optional — defaults to http://localhost:8000
# EFFICIENTAI_API_BASE=https://staging.efficientai.cloud
```

No `agent_id` required for WebRTC. Each call gets its own Call ID automatically — do **not** set `EFFICIENTAI_CALL_SHORT_ID` in `.env`.

### The three hooks

| Step | Function | What it does |
|------|----------|--------------|
| 1 | `ensure_trace_session()` | Mints Call ID; opens trace row on EfficientAI |
| 2 | `setup_pipecat_worker_tracing(trace_ctx)` | OTLP export + `efficientai.call_short_id` on every span |
| 3 | `close_trace_session(trace_ctx)` | Flush spans; mark trace **closed** on disconnect |

### WebRTC — `PipelineWorker` (recommended)

Copy a full example or use this minimum pattern:

```python
from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    require_deployment_trace_env,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
)

require_deployment_trace_env()  # checks EFFICIENTAI_API_KEY + WORKSPACE_ID

async def run_bot(transport, runner_args):
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

    # See docs/examples/*.py for WorkerRunner setup
```

### Alternative — `PipelineTask` (phone / older style)

```python
from efficientai.integrations.efficientai_traces import configure_pipecat_tracing

task = PipelineTask(
    pipeline,
    **configure_pipecat_tracing(call_short_id=call_short_id),
)
```

See `docs/examples/pipecat_inbound_phone_tracing.py` (call ID from SIP headers).

### Playground WebSocket handshake

```python
configure_pipecat_tracing(handshake=message)
```

EfficientAI sends `call_short_id` in the handshake — no manual session call needed.

### Example bots

| Use case | File |
|----------|------|
| Multi-agent WebRTC (Fireworks + ElevenLabs) | `docs/examples/pipecat_multi_agent_webrtc_tracing.py` |
| Single agent, swap STT/LLM/TTS | `docs/examples/pipecat_multi_provider_webrtc_tracing.py` |
| Gemini Live / S2S | `docs/examples/pipecat_upstream_webrtc_tracing.py` |
| Custom WebSocket | `docs/examples/pipecat_upstream_websocket_tracing.py` |
| Inbound phone (SIP) | `docs/examples/pipecat_inbound_phone_tracing.py` |
| Env template | `docs/examples/pipecat.env.example` |

---

## Customer checklist

1. Create API key; copy workspace UUID (Call Traces → Connect Pipecat).
2. Add `EFFICIENTAI_API_KEY` and `EFFICIENTAI_WORKSPACE_ID` to Pipecat `.env`.
3. Copy an example `bot.py`; wire the three hooks above.
4. Run `eai start-all` (local) or point `EFFICIENTAI_API_BASE` at staging.
5. WebRTC call at `http://localhost:7860/client` → disconnect.
6. **Call Traces** → Refresh → open your Call ID.

---

## Quick start (local WebRTC)

### 1. Install

See [Pipecat integration](#install) above.

### 2. Bot script

Recommended: copy `docs/examples/pipecat_multi_agent_webrtc_tracing.py` → `bot.py`

### 3. Run

```bash
# Terminal 1 — EfficientAI
eai start-all

# Terminal 2 — Pipecat
uv run bot.py
```

### 4. Connect

Open **http://localhost:7860/client** → WebRTC → Connect → talk 2–3 turns → disconnect.

### 5. View traces

**Call Traces** in the UI → **Refresh** → open the row with your Call ID.

---

## API reference

Base paths (append to `/api/v1`):

| Environment | Base |
|-------------|------|
| Local | `http://localhost:8000` |
| Staging | `https://staging.efficientai.cloud` |

### Create session

`ensure_trace_session()` calls this automatically.

```bash
curl -X POST https://staging.efficientai.cloud/api/v1/observability/traces/sessions \
  -H "X-API-Key: <key>" \
  -H "X-Workspace-Id: <workspace-uuid>" \
  -H "Content-Type: application/json" \
  -d '{"transport":"webrtc"}'
```

### Export spans (OTLP)

```http
POST /api/v1/observability/traces
```

| Header | Value |
|--------|-------|
| `X-API-Key` | API key |
| `X-Workspace-Id` | workspace uuid |
| `X-EfficientAI-Call-Short-Id` | 6-digit call id |

Also set on spans: `efficientai.call_short_id`, `efficientai.workspace_id`.

### Close session

```bash
curl -X POST https://staging.efficientai.cloud/api/v1/observability/traces/sessions/482931/close \
  -H "X-API-Key: <key>" \
  -H "X-Workspace-Id: <workspace-uuid>"
```

### Span attributes (Pipecat native tracing)

| Attribute | Purpose |
|-----------|---------|
| `efficientai.call_short_id` | Links spans to the call |
| `efficientai.workspace_id` | Workspace scope |
| `gen_ai.operation.name` | `stt` / `llm` / `tts` / `s2s` |
| `gen_ai.request.model` | Model name in UI |
| `metrics.ttfb` | Time to first byte (**seconds**) |
| `turn.number` | Turn index |

### Setup endpoint (UI uses this)

```http
GET /api/v1/observability/traces/setup
```

Returns OTLP URL, env block, and Python snippet for the active host.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Transport 'webrtc' is disabled` | `pip install pipecat-ai[webrtc]`; add `webrtc` to `transport_params` |
| No traces in UI | Check API key + workspace ID; Refresh |
| `correlated: false` on ingest | Missing `call_short_id` on spans or headers |
| Call ID in logs but empty trace | `enable_tracing=True` on `PipelineWorker`; install `efficientAI[otel]` |
| Trace stays open | Call `close_trace_session()` on disconnect |
| Wrong workspace | Switch workspace in UI — list is workspace-scoped |
| Local bot, staging UI empty | Set `EFFICIENTAI_API_BASE=https://staging.efficientai.cloud` |

---

## Other transports

WebSocket and phone use the same OTLP URL and Call ID correlation. See `docs/examples/pipecat_inbound_phone_tracing.py` for SIP header flow.
