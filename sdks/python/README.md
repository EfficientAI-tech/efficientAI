# EfficientAI Python SDK

The official Python client for [EfficientAI](https://efficientai.cloud). Use it to send live traces from your voice and chat agents, run simulations, and read evaluation results.

> **Status: alpha (0.x).** The client core is in place. Live tracing and simulations are being added; see the [changelog](CHANGELOG.md).

## Install

```bash
pip install efficientai-sdk
# with OpenTelemetry tracing support
pip install "efficientai-sdk[otel]"
```

Requires Python 3.9 or newer.

## Configure

EfficientAI is self-hosted, so point the SDK at your own deployment. If no URL is set, it uses `http://localhost:8000`.

Create an API key in your EfficientAI dashboard. Then either set environment variables:

```bash
export EFFICIENTAI_BASE_URL="https://efficientai.your-company.com"  # your deployment; default http://localhost:8000
export EFFICIENTAI_API_KEY="..."
export EFFICIENTAI_WORKSPACE_ID="..."  # optional; the key's default workspace is used otherwise
```

or pass the same values to the client:

```python
from efficientai_sdk import EfficientAI

client = EfficientAI(
    base_url="https://efficientai.your-company.com",
    api_key="...",
    workspace_id="...",
)
client.verify()  # True, or raises AuthenticationError
```

An async client with the same arguments is available:

```python
from efficientai_sdk import AsyncEfficientAI

async with AsyncEfficientAI() as client:
    await client.verify()
```

## Live call tracing

Install the `otel` extra, then wrap each call in a trace session. Spans created inside the session are tagged with the call's id and exported to EfficientAI. The session closes when the block ends.

```python
from efficientai_sdk import AsyncEfficientAI

efficientai = AsyncEfficientAI()


async def handle_call(first_message=None):
    async with efficientai.trace.session(transport="websocket", handshake=first_message) as call:
        with call.turn():
            with call.stt(model="nova-3", provider="deepgram") as stt:
                stt.set_transcript(user_text)
            with call.llm(model="gpt-4o", provider="openai") as llm:
                llm.set_output(reply).set_ttfb(0.31)
            with call.tts(model="sonic", provider="cartesia") as tts:
                tts.set_text(reply)
```

- **Pipecat:** `PipelineTask(pipeline, **task_kwargs(call))` with `from efficientai_sdk.integrations.pipecat import task_kwargs`.
- **Existing OpenTelemetry setup:** call `efficientai.trace.instrument()` once at startup.
- **Test calls from EfficientAI:** pass the platform's `handshake=`, `headers=` or `sip_headers=` so traces link to the simulation result.
- **Concurrent calls:** each session is tracked per asyncio task, so one process can serve many calls.
- **Failures:** tracing never breaks a call. If EfficientAI is unreachable, the call runs untraced and a warning is logged. Pass `strict=True` to raise instead.

A runnable example is in [`examples/custom_agent_tracing.py`](examples/custom_agent_tracing.py). The full guide is on the "Python SDK" page of the EfficientAI docs.

## Errors and retries

Every error the SDK raises inherits from `EfficientAIError`.

| Exception | When |
|---|---|
| `ConfigurationError` | Missing API key or invalid settings |
| `APIConnectionError` / `APITimeoutError` | The server could not be reached |
| `AuthenticationError` | 401: the key is invalid or inactive |
| `PermissionDeniedError` | 403 |
| `NotFoundError` | 404 |
| `UnprocessableEntityError` | 422: the request failed validation |
| `RateLimitError` | 429; `retry_after` holds the server's hint |
| `InternalServerError` | 5xx |

The client retries failed requests up to `max_retries` times (default 2), with exponential backoff and jitter. It honours the server's `Retry-After` header.
- `GET`, `PUT` and `DELETE` retry on timeouts, 408, 429 and 5xx responses.
- `POST` and `PATCH` retry only when the server certainly didn't process the request: 429, 503, or a failed connection.

Set `max_retries=0` to turn retries off.

## Development

```bash
cd sdks/python
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Releases are published to PyPI from tags named `sdk-py-v<version>`, which must match `src/efficientai_sdk/_version.py`.
