# GET /api/v1/call-imports

List Call Imports

- Operation ID: `listCallImports`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `page` (query, optional) `integer`
- `page_size` (query, optional) `integer`
- `status` (query, optional)
- `dataset` (query, optional)
  - Filter by exact dataset string (case-insensitive). Pass the literal value '__none__' to filter to imports with no dataset.
- `tag_id` (query, optional)
  - Filter to imports tagged with ALL of the given tag ids.
- `source_format` (query, optional)
  - Filter by source format. Use 'audio' for manual recordings or '__non_audio__' for CSV/Excel/legacy imports.
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/call-imports" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

