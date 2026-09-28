# Pipecat & OTLP integration

Per-turn **STT, LLM, and TTS timing** from your Pipecat agent show in **Calls → Traces** (`/observability/calls`).

**Default path:** [sandbox](https://sandbox.efficientai.cloud) — you do **not** run EfficientAI on your laptop. **Local** is only for core platform dev (`eai start-all`); use a **different** workspace UUID than sandbox.

Related: Call Traces overview · Latency metrics · Architecture & scaling

---

## Terms (30 seconds)

| Term | Meaning |
| --- | --- |
| **Sandbox / local** | `https://sandbox.efficientai.cloud` vs `http://localhost:8000` — pick one; never mix workspace IDs |
| **`EFFICIENTAI_API_BASE`** | REST host (sessions, setup) |
| **`EFFICIENTAI_OTLP_ENDPOINT`** | `{base}/api/v1/observability/traces` |
| **`EFFICIENTAI_WORKSPACE_ID`** | Workspace UUID (header switcher) — traces land here |
| **`EFFICIENTAI_API_KEY`** | Settings → API keys |
| **Call ID** | Six-digit `call_short_id` from `ensure_trace_session()` — **do not** put in `.env` |
| **Setup API** | `GET /api/v1/observability/traces/setup` → `env_block` + snippets |

---

## Quickstart — sandbox (copy-paste)

### 1. In the browser (once)

1. Log in to [sandbox](https://sandbox.efficientai.cloud).
2. Select the **workspace** where you will view traces.
3. **Settings → API keys** → create and copy a key.
4. Note the workspace **UUID** (org/workspace settings or header switcher).

### 2. Create `pipecat-agent` and get `bot.py` + `.env`

```bash
mkdir -p /path/to/work/pipecat-agent && cd /path/to/work/pipecat-agent
uv venv && source .venv/bin/activate

EXAMPLES="https://raw.githubusercontent.com/EfficientAI-tech/efficientAI/otel-traces/docs/examples"
```

**Pick one example** (or use your own bot — see [Pipecat hooks](#pipecat-hooks) below):

| Bot | Download |
| --- | --- |
| Multi-agent WebRTC (Fireworks + ElevenLabs) | `curl -fsSL "$EXAMPLES/pipecat_multi_agent_webrtc_tracing.py" -o bot.py` |
| Gemini Live WebRTC | `curl -fsSL "$EXAMPLES/pipecat_upstream_webrtc_tracing.py" -o bot.py` |

```bash
curl -fsSL "$EXAMPLES/pipecat.env.example" -o .env
```

**Fill `.env`** — either:

- **Setup API** (paste `env_block`, then add provider keys):

```bash
curl -s "https://sandbox.efficientai.cloud/api/v1/observability/traces/setup" \
  -H "X-API-Key: <key>" \
  -H "X-Workspace-Id: <workspace-uuid>"
```

- **Manual:** set `EFFICIENTAI_API_BASE`, `EFFICIENTAI_OTLP_ENDPOINT`, `EFFICIENTAI_WORKSPACE_ID`, `EFFICIENTAI_API_KEY`, plus `FIREWORKS_API_KEY` / `ELEVENLABS_API_KEY` / `GOOGLE_API_KEY` as needed.

Local clone instead of `curl`? Copy from `docs/examples/` in the [efficientAI repo](https://github.com/EfficientAI-tech/efficientAI) (same parent folder as `pipecat-agent` is fine).

### 3. Install

```bash
uv pip install "pipecat-ai[silero,elevenlabs,fireworks,deepgram,runner,webrtc]>=1.4.0"
uv pip install python-dotenv loguru httpx
uv pip install "efficientai[otel] @ git+https://github.com/EfficientAI-tech/efficientAI.git@otel-traces"
# Local SDK dev: uv pip install -e '/path/to/work/efficientAI[otel]'
# After PyPI: uv pip install "efficientai[otel]"
```

Voice runs without EfficientAI; tracing needs SDK + env above.

### 4. Preflight (recommended)

```bash
curl -i -X POST "https://sandbox.efficientai.cloud/api/v1/observability/traces/sessions" \
  -H "X-API-Key: YOUR_KEY" \
  -H "X-Workspace-Id: YOUR_WORKSPACE_UUID" \
  -H "Content-Type: application/json" \
  -d '{"transport":"webrtc"}'
```

Expect **HTTP 200** and `call_short_id`. **404** → wrong base URL or workspace.

### 5. Run and verify

```bash
uv run bot.py
```

1. Open **http://localhost:7860/client** → WebRTC → speak → disconnect.
2. In sandbox (same workspace as `.env`): **Observability → Calls** → Refresh → open the Call ID.
3. Wait a few seconds after hang-up (**worker-traces** ingest).

`EfficientAI tracing off` in logs → fix `.env`; voice is intentionally not blocked.

**Calls vs S3:** The Calls hub shows processed traces for the UI workspace. **Data Sources → S3** may show raw `traces/.../workspaces/<uuid>/` WAL files — those alone do not appear as Calls rows until ingested.

---

## Pipecat hooks {#pipecat-hooks}

Our example `bot.py` files already wire this. For your own bot:

| Order | Call | Purpose |
| --- | --- | --- |
| 1 | `warn_deployment_trace_env()` | Log missing env (optional) |
| 2 | `ensure_trace_session()` | Session + Call ID (`enabled: false` on failure — voice continues) |
| 3 | `setup_pipecat_worker_tracing(trace_ctx)` | OTLP + headers |
| 4 | `PipelineWorker(..., enable_tracing=tracing["enabled"])` | Pipecat spans |
| 5 | `close_trace_session(trace_ctx)` on disconnect | Flush |

```python
from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
    warn_deployment_trace_env,
)

warn_deployment_trace_env()

async def run_bot(transport, runner_args):
    trace_ctx = await ensure_trace_session(
        transport=resolve_trace_transport(runner_args, transport),
    )
    tracing = setup_pipecat_worker_tracing(trace_ctx)

    worker = PipelineWorker(
        pipeline,
        enable_tracing=bool(tracing.get("enabled")),
        additional_span_attributes=tracing.get("additional_span_attributes") or {},
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await worker.cancel()
        await close_trace_session(trace_ctx)
```

---

## Local EfficientAI (platform dev only)

```bash
# Terminal 1
eai start-all   # include worker-traces

# Terminal 2 — new workspace UUID + key from localhost UI
EFFICIENTAI_API_BASE=http://localhost:8000
EFFICIENTAI_OTLP_ENDPOINT=http://localhost:8000/api/v1/observability/traces
uv run bot.py
```

UI: http://localhost:8000 — do **not** reuse sandbox workspace UUID in `.env`.

---

## How it works

```
ensure_trace_session() → Call ID → Pipecat spans (OTLP) → worker-traces → ClickHouse → Calls hub → close_trace_session()
```

---

## More example bots

| Use case | File under `docs/examples/` |
| --- | --- |
| Multi-provider WebRTC | `pipecat_multi_provider_webrtc_tracing.py` |
| WebSocket | `pipecat_upstream_websocket_tracing.py` |
| Inbound phone | `pipecat_inbound_phone_tracing.py` |

Same `EXAMPLES` GitHub base URL as quickstart. Template: `pipecat.env.example`.

---

## API reference (sandbox)

| Action | Method & path |
| --- | --- |
| Setup helper | `GET /api/v1/observability/traces/setup` |
| Open call | `POST /api/v1/observability/traces/sessions` |
| Ingest spans | `POST /api/v1/observability/traces` |

Headers for session + OTLP: `X-API-Key`, `X-Workspace-Id`, and for spans `X-EfficientAI-Call-Short-Id` (plus span attribute `efficientai.call_short_id`).

Ingest may return **202**; UI updates after worker commit. **Not used:** `POST …/observability/live/events`.

### LiveKit / custom stacks

Same session API, then OTLP HTTP to `trace_ctx["otlp_endpoint"]` with the headers above.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Connection error on start | Use **https** sandbox URL, not dead `localhost` |
| Sessions **404** | Wrong `EFFICIENTAI_API_BASE` |
| No traces in UI | Key + workspace match UI; Refresh; worker-traces running |
| Delay after hang-up | Normal (deferred ingest) |
| UI empty, bot runs | `.env` points at localhost but you check **sandbox** UI |
| Trace stays open | Call `close_trace_session()` on disconnect |

WebSocket and phone bots use the same env vars and session API.
