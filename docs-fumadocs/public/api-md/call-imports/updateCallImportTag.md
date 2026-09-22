# PATCH /api/v1/call-import-tags/{tag_id}

Update Call Import Tag

- Operation ID: `updateCallImportTag`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `tag_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X PATCH "http://localhost:8000/api/v1/call-import-tags/{tag_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

