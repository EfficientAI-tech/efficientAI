# PUT /api/v1/agents/{agent_id}

Update Agent

- Operation ID: `update_agent_api_v1_agents__agent_id__put`
- Tags: `Agents`
- Auth: Bearer or API Key

## Parameters

- `agent_id` (path, required) `string`
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
curl -X PUT "http://localhost:8000/api/v1/agents/{agent_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

