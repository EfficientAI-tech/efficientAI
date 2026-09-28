# POST /api/v1/observability/traces

Ingest OTLP trace spans (HTTP/protobuf or JSON)

- Operation ID: `ingestObservabilityTracesOtlp`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `X-EfficientAI-Run-Id` (header, optional)
- `X-EfficientAI-Agent-Id` (header, optional)
- `X-EfficientAI-Call-Short-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `202` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/observability/traces" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

