# POST /api/v1/observability/traces/sessions/{call_short_id}/close

Close Trace Session Route

- Operation ID: `closeObservabilityTraceSession`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `call_short_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/observability/traces/sessions/{call_short_id}/close" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

