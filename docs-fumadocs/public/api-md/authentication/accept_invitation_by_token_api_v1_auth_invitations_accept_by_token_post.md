# POST /api/v1/auth/invitations/accept-by-token

Accept Invitation By Token

- Operation ID: `accept_invitation_by_token_api_v1_auth_invitations_accept_by_token_post`
- Tags: `Authentication`
- Auth: Bearer or API Key

## Parameters

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
curl -X POST "http://localhost:8000/api/v1/auth/invitations/accept-by-token" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

