# POST /api/v1/observability/traces/ingest

Ingest Json Traces

- Operation ID: `ingestObservabilityTracesJson`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/observability/traces/ingest" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

