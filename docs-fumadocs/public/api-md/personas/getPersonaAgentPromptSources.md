# GET /api/v1/personas/agent-prompt-sources/{agent_id}

Get Agent Prompt Sources

- Operation ID: `getPersonaAgentPromptSources`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `agent_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/personas/agent-prompt-sources/{agent_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

