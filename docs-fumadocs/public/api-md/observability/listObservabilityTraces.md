# GET /api/v1/observability/traces

List Observability Traces

- Operation ID: `listObservabilityTraces`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `skip` (query, optional) `integer`
- `limit` (query, optional) `integer`
- `status` (query, optional)
  - open or closed
- `cursor` (query, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/observability/traces" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

