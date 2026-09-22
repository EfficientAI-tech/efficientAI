# POST /api/v1/call-imports/{call_import_id}/retry-failed

Retry Failed Call Import Rows

- Operation ID: `retryFailedCallImportRows`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `call_import_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `202` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/call-imports/{call_import_id}/retry-failed" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

