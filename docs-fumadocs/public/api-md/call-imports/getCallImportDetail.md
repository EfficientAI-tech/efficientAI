# GET /api/v1/call-imports/{call_import_id}

Get Call Import Detail

- Operation ID: `getCallImportDetail`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `call_import_id` (path, required) `string`
- `row_limit` (query, optional) `integer`
- `row_offset` (query, optional) `integer`
- `q` (query, optional)
  - Optional case-insensitive substring filter on ``conversation_id``. When set, ``filtered_total_rows`` in the response reflects the post-filter row count so the UI can paginate against the filtered slice.
- `diarised_status` (query, optional)
  - Optional filter on ``CallImportRow.diarised_transcript_status``. Accepts one of ``pending``, ``running``, ``completed``, ``failed``. When set, ``filtered_total_rows`` reflects the post-filter row count (combined with the ``q`` filter when both are supplied) so the UI can paginate against the same slice it's displaying.
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/call-imports/{call_import_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

