# PUT /api/v1/aiproviders/{aiprovider_id}

Update Aiprovider

- Operation ID: `updateAIProvider`
- Tags: `AI Providers`
- Auth: Bearer or API Key

## Parameters

- `aiprovider_id` (path, required) `string`
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
curl -X PUT "http://localhost:8000/api/v1/aiproviders/{aiprovider_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

