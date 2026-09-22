# POST /api/v1/agents/{agent_id}/sync-provider-prompt

Sync Agent Provider Prompt

- Operation ID: `sync_agent_provider_prompt_api_v1_agents__agent_id__sync_provider_prompt_post`
- Tags: `Agents`
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
curl -X POST "http://localhost:8000/api/v1/agents/{agent_id}/sync-provider-prompt" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

