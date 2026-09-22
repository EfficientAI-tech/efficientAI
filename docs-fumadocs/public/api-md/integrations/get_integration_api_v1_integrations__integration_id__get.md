# GET /api/v1/integrations/{integration_id}

Get Integration

- Operation ID: `get_integration_api_v1_integrations__integration_id__get`
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
curl -X GET "http://localhost:8000/api/v1/integrations/{integration_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

