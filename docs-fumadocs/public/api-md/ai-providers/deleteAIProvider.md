# DELETE /api/v1/aiproviders/{aiprovider_id}

Delete Aiprovider

- Operation ID: `deleteAIProvider`
- Tags: `AI Providers`
- Auth: Bearer or API Key

## Parameters

- `aiprovider_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `204` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/aiproviders/{aiprovider_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

