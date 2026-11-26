# Changelog

All notable changes to `efficientai-sdk` are recorded here. The project follows [semantic versioning](https://semver.org); while in 0.x, minor versions may include breaking changes.

## 0.1.0 (unreleased)

- `EfficientAI` and `AsyncEfficientAI` clients, configured from arguments or `EFFICIENTAI_*` environment variables. The base URL defaults to `http://localhost:8000` for self-hosted deployments.
- `verify()` checks an API key against the server.
- Typed exception hierarchy rooted at `EfficientAIError`.
- Automatic retries with exponential backoff, jitter and `Retry-After` support.
- `efficientai_sdk.tracing`: trace sessions, OTLP export with correlation headers and span attributes, handshake parsing, and SIP/webhook correlation helpers. These moved here from `efficientai.integrations.efficientai_traces`, which now re-exports them.
- `efficientai_sdk.integrations.pipecat`: `configure_pipecat_tracing` and related helpers.
- Fix: when the app already has its own `TracerProvider`, the EfficientAI exporter is now added to it. Previously spans were never exported in that case.
- Trace contexts now carry `evaluator_result_id` from the platform handshake, so spans link to simulation results.
