# POST /api/v1/observability/traces/backfill

Backfill Traces

- Operation ID: `backfillObservabilityTraces`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `limit` (query, optional) `integer`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/observability/traces/backfill" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

