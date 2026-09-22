# GET /api/v1/call-imports/{call_import_id}/row-ids

List Call Import Row Ids

- Operation ID: `listCallImportRowIds`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `call_import_id` (path, required) `string`
- `q` (query, optional)
  - Optional case-insensitive substring filter on ``conversation_id``. Same semantics as the detail endpoint.
- `diarised_status` (query, optional)
  - Optional filter on ``CallImportRow.diarised_transcript_status``. Accepts ``pending`` / ``running`` / ``completed`` / ``failed``.
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/call-imports/{call_import_id}/row-ids" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

