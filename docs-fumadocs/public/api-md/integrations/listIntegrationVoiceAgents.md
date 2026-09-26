# GET /api/v1/integrations/{integration_id}/voice-agents

List Integration Voice Agents Route

- Operation ID: `listIntegrationVoiceAgents`
- Tags: `Integrations`
- Auth: Bearer or API Key

## Parameters

- `integration_id` (path, required) `string`
- `refresh` (query, optional) `boolean`
- `search` (query, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/integrations/{integration_id}/voice-agents" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

