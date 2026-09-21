# DELETE /api/v1/agents/{agent_id}

Delete Agent

- Operation ID: `delete_agent_api_v1_agents__agent_id__delete`
- Tags: `Agents`
- Auth: Bearer or API Key

## Parameters

- `agent_id` (path, required) `string`
- `force` (query, optional) `boolean`
  - Force delete with all dependent records
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/agents/{agent_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

