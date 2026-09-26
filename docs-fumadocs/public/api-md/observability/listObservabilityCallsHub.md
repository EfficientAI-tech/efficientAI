# GET /api/v1/observability/calls-hub

Merged telephony calls and OTLP traces feed

- Operation ID: `listObservabilityCallsHub`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `skip` (query, optional) `integer`
- `limit` (query, optional) `integer`
- `status` (query, optional)
  - Trace status filter: open, closed, or omit for all
- `search` (query, optional)
- `event` (query, optional) `string`
  - Telephony event filter
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/observability/calls-hub" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

