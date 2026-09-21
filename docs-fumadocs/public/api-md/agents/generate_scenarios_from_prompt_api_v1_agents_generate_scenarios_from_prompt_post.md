# POST /api/v1/agents/generate-scenarios-from-prompt

Generate Scenarios From Prompt

- Operation ID: `generate_scenarios_from_prompt_api_v1_agents_generate_scenarios_from_prompt_post`
- Tags: `Agents`
- Auth: Bearer or API Key

## Parameters

- `X-Workspace-Id` (header, optional)
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
curl -X POST "http://localhost:8000/api/v1/agents/generate-scenarios-from-prompt" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

