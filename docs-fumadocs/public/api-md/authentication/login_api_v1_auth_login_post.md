# POST /api/v1/auth/login

Login

- Operation ID: `login_api_v1_auth_login_post`
- Tags: `Authentication`
- Auth: Public

## Request Body

See schema in API reference UI.

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

