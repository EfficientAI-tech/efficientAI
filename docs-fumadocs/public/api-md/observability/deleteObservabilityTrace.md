# DELETE /api/v1/observability/traces/{trace_id}

Delete Observability Trace

- Operation ID: `deleteObservabilityTrace`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `trace_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/observability/traces/{trace_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

