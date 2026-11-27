# Changelog

All notable changes to `efficientai-sdk` are recorded here. The project follows [semantic versioning](https://semver.org); while in 0.x, minor versions may include breaking changes.

## 0.1.0 (unreleased)

- `EfficientAI` and `AsyncEfficientAI` clients, configured from arguments or `EFFICIENTAI_*` environment variables. The base URL defaults to `http://localhost:8000` for self-hosted deployments.
- `verify()` checks an API key against the server.
- Typed exception hierarchy rooted at `EfficientAIError`.
- Automatic retries with exponential backoff, jitter and `Retry-After` support.
- `efficientai_sdk.tracing`: trace sessions, OTLP export with correlation headers and span attributes, handshake parsing, and SIP/webhook correlation helpers. These moved here from `efficientai.integrations.efficientai_traces`, which now re-exports them.
- `efficientai_sdk.integrations.pipecat`: `configure_pipecat_tracing` and related helpers.
- `client.trace.session(...)` (sync and async): one trace session per call, with `turn`, `stt`, `llm`, `tts`, `s2s` and `span` helpers that emit spans in the format EfficientAI maps to turns and latencies. Reuses the platform's call id from a handshake, HTTP headers or SIP headers.
- `client.trace.instrument()` exports an existing OpenTelemetry setup to EfficientAI.
- `efficientai_sdk.integrations.pipecat.task_kwargs(call)`.
- Chat agents: `session(channel="chat")`, `call.user_message()`, `call.assistant_message()`, `call.tool()` and `call.retrieval()`. Long attribute values are truncated at 8,192 characters.
- Call correlation is now tracked per asyncio task / context, so concurrent calls in one process no longer mix spans. This also applies to the older `setup_worker_tracing` / `setup_efficientai_tracing` helpers.
- Fix: when the app already has its own `TracerProvider`, the EfficientAI exporter is now added to it. Previously spans were never exported in that case.
- Trace contexts now carry `evaluator_result_id` from the platform handshake, so spans link to simulation results.
