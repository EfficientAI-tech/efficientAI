# GET /api/v1/integrations/{integration_id}/api-key

Get Integration Api Key

- Operation ID: `get_integration_api_key_api_v1_integrations__integration_id__api_key_get`
- Tags: `Integrations`
- Auth: Bearer or API Key

## Parameters

- `integration_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/integrations/{integration_id}/api-key" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

