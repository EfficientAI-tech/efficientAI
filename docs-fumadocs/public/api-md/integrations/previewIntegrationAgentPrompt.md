# POST /api/v1/integrations/{integration_id}/preview-agent-prompt

Preview Integration Agent Prompt

- Operation ID: `previewIntegrationAgentPrompt`
- Tags: `Integrations`
- Auth: Bearer or API Key

## Parameters

- `integration_id` (path, required) `string`
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
curl -X POST "http://localhost:8000/api/v1/integrations/{integration_id}/preview-agent-prompt" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

