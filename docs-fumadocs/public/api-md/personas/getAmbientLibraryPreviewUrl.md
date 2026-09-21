# GET /api/v1/personas/ambient-library/{asset_id}/preview-url

Get Ambient Library Preview Url

- Operation ID: `getAmbientLibraryPreviewUrl`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `asset_id` (path, required) `string`
- `expiration` (query, optional) `integer`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/personas/ambient-library/{asset_id}/preview-url" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

