# POST /api/v1/call-imports/{call_import_id}/rows/{row_id}/diarised-speaker-swap

Toggle Call Import Row Speaker Swap

- Operation ID: `toggleCallImportRowSpeakerSwap`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `call_import_id` (path, required) `string`
- `row_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/call-imports/{call_import_id}/rows/{row_id}/diarised-speaker-swap" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

