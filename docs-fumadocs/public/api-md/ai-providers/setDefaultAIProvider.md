# POST /api/v1/aiproviders/{aiprovider_id}/set-default

Set Default Aiprovider

- Operation ID: `setDefaultAIProvider`
- Tags: `AI Providers`
- Auth: Bearer or API Key

## Parameters

- `aiprovider_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/aiproviders/{aiprovider_id}/set-default" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

