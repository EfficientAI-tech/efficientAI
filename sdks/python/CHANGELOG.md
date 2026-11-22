# Changelog

All notable changes to `efficientai-sdk` are recorded here. The project follows [semantic versioning](https://semver.org); while in 0.x, minor versions may include breaking changes.

## 0.1.0 (unreleased)

- `EfficientAI` and `AsyncEfficientAI` clients, configured from arguments or `EFFICIENTAI_*` environment variables. The base URL defaults to `http://localhost:8000` for self-hosted deployments.
- `verify()` checks an API key against the server.
- Typed exception hierarchy rooted at `EfficientAIError`.
- Automatic retries with exponential backoff, jitter and `Retry-After` support.
