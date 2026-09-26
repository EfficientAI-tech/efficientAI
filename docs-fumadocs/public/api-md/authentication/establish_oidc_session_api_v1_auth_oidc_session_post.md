# POST /api/v1/auth/oidc/session

Establish Oidc Session

- Operation ID: `establish_oidc_session_api_v1_auth_oidc_session_post`
- Tags: `Authentication`
- Auth: Bearer or API Key

## Parameters

- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/auth/oidc/session" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

