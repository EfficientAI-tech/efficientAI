# GET /api/v1/call-imports/{call_import_id}/insights

Get Call Import Insights

- Operation ID: `getCallImportInsights`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `call_import_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/call-imports/{call_import_id}/insights" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

