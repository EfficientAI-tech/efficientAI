# GET /api/v1/observability/calls

List Calls

- Operation ID: `list_calls_api_v1_observability_calls_get`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `skip` (query, optional) `integer`
- `limit` (query, optional) `integer`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/observability/calls" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

