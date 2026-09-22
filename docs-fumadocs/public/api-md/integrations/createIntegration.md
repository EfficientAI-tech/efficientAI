# POST /api/v1/integrations

Create Integration

- Operation ID: `createIntegration`
- Tags: `Integrations`
- Auth: Bearer or API Key

## Parameters

- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `201` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/integrations" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

