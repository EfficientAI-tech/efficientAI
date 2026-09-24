# POST /api/v1/auth/refresh

Refresh Session

- Operation ID: `refresh_session_api_v1_auth_refresh_post`
- Tags: `Authentication`
- Auth: Public

## Parameters

- `Authorization` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/auth/refresh" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

