# GET /api/v1/auth/invitations/preview/{token}

Preview Invitation

- Operation ID: `preview_invitation_api_v1_auth_invitations_preview__token__get`
- Tags: `Authentication`
- Auth: Public

## Parameters

- `token` (path, required) `string`

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/auth/invitations/preview/{token}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

