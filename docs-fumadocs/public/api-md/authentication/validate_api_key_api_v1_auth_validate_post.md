# POST /api/v1/auth/validate

Validate Api Key

- Operation ID: `validate_api_key_api_v1_auth_validate_post`
- Tags: `Authentication`
- Auth: Bearer or API Key

## Parameters

- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `Authorization` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/auth/validate" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

