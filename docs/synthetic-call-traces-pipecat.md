# Call Traces — Pipecat integration

Connect a **Pipecat voice agent on your computer** to EfficientAI. Traces show up under **Observability → Calls** (`/observability/calls`).

Follow the quickstart below or the full guide: `docs/confluence-fumadocs-archive/monitoring/call-traces/04-pipecat-otlp-integration.md` · [public docs](https://docs.efficientai.cloud/docs/monitoring/call-traces/pipecat-integration/).

Pick **one** setup path below — **sandbox** (hosted) or **local** (you run the API). Do not point a sandbox workspace at `localhost` or vice versa.

---

## Lab quickstart

Matches **Fumadocs archive** / Confluence **Pipecat & OTLP integration** (quickstart section). For your machine with a local clone, use `cp` from `efficientAI/docs/examples/` instead of GitHub `curl` in that doc.

Confluence copy: `docs/confluence-fumadocs-archive/monitoring/call-traces/04-pipecat-otlp-integration.md` (lab section included)

---

## What each piece is

| Piece | What it is |
| --- | --- |
| **Sandbox** | Hosted EfficientAI at `https://sandbox.efficientai.cloud` — no local install |
| **Local EfficientAI** | API on your machine (`eai start-all`, port 8000) — for core dev only |
| **`EFFICIENTAI_API_BASE`** | REST API host (sessions, setup). Must match where you log in |
| **`EFFICIENTAI_OTLP_ENDPOINT`** | Where spans are POSTed (`…/api/v1/observability/traces`) |
| **`EFFICIENTAI_WORKSPACE_ID`** | UUID of the workspace shown in the UI header — traces are scoped here |
| **`EFFICIENTAI_API_KEY`** | From **Settings → API keys** |
| **`ensure_trace_session()`** | Opens a trace; EfficientAI assigns a six-digit **Call ID** |
| **`setup_pipecat_worker_tracing()`** | Wires OTLP export + headers (`X-Workspace-Id`, Call ID) |
| **`enable_tracing=True`** | Pipecat emits STT / LLM / TTS spans |
| **`close_trace_session()`** | Flushes spans and closes the trace on hang-up |

Do **not** set `EFFICIENTAI_CALL_SHORT_ID` in `.env` — one Call ID per call, created at session start.

---

## Path A — Sandbox (recommended for integrations)

### 1. EfficientAI (browser)

1. Log in: https://sandbox.efficientai.cloud  
2. Select the **workspace** where you want traces  
3. **Settings → API keys** → create a key → copy it  

### 2. Pipecat `.env` (your machine)

Use `GET /api/v1/observability/traces/setup` (headers: `X-API-Key`, `X-Workspace-Id`) and paste `env_block`, or:

```env
EFFICIENTAI_API_BASE=https://sandbox.efficientai.cloud
EFFICIENTAI_OTLP_ENDPOINT=https://sandbox.efficientai.cloud/api/v1/observability/traces
EFFICIENTAI_WORKSPACE_ID=<workspace UUID — header switcher or setup API>
EFFICIENTAI_API_KEY=<from Settings → API keys>

DEEPGRAM_API_KEY=...
OPENAI_API_KEY=...
```

### 3. Install (once per project)

```bash
pip install "pipecat-ai[silero,deepgram,openai,cartesia,runner,webrtc]>=1.4.0"
pip install "efficientai[otel] @ git+https://github.com/EfficientAI-tech/efficientAI.git"
```

### 4. Preflight (optional)

Session API must return **200** (404 usually means wrong base URL or old API):

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST "https://sandbox.efficientai.cloud/api/v1/observability/traces/sessions" \
  -H "X-API-Key: $EFFICIENTAI_API_KEY" \
  -H "X-Workspace-Id: $EFFICIENTAI_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"transport":"webrtc"}'
```

### 5. Bot hooks — see Part 3 below

### 6. Run and verify

```bash
uv run bot.py
```

WebRTC client (example): **http://localhost:7860/client** → Connect → speak → Disconnect.

In **sandbox** UI: **Calls** → **Refresh** → open the Call ID row.

---

## Path B — Local EfficientAI (optional)

Use this only when you run the full stack locally.

### Terminal 1 — EfficientAI

```bash
eai start-all
```

Confirm **`worker-traces`** is running (deferred ingest needs it).

### Terminal 2 — Pipecat `.env`

Use a **local** workspace ID (not your sandbox workspace):

```env
EFFICIENTAI_API_BASE=http://localhost:8000
EFFICIENTAI_OTLP_ENDPOINT=http://localhost:8000/api/v1/observability/traces
EFFICIENTAI_WORKSPACE_ID=<local workspace uuid>
EFFICIENTAI_API_KEY=<local key>
```

Same install and bot hooks as sandbox. UI: http://localhost:8000

---

## Part 3 — Three hooks in `bot.py`

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

Full examples: `docs/examples/pipecat_multi_agent_webrtc_tracing.py`, `pipecat_multi_provider_webrtc_tracing.py`

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `ConnectError` / connection failed on start | `EFFICIENTAI_API_BASE` is reachable (sandbox **https**, not dead `localhost`) |
| `POST …/traces/sessions` **404** | Wrong host or API version; use sandbox URL above |
| Bot crashes on start | `EFFICIENTAI_API_KEY` and `EFFICIENTAI_WORKSPACE_ID` set |
| UI empty after call | Base URL + workspace match where you are logged in; **Refresh** |
| Call in wrong workspace | OTLP and session must use same `X-Workspace-Id` (SDK sends it when env is set) |
| Call ID but empty trace | `enable_tracing=True` + `efficientai[otel]` installed |
| Trace stays open | `close_trace_session()` on disconnect |

---

## Other transports

WebSocket and phone use the same env vars and session API. See `docs/examples/pipecat_inbound_phone_tracing.py`.
