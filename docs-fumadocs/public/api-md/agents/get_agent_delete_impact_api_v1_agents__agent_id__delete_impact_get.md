# GET /api/v1/agents/{agent_id}/delete-impact

Get Agent Delete Impact

- Operation ID: `get_agent_delete_impact_api_v1_agents__agent_id__delete_impact_get`
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
curl -X GET "http://localhost:8000/api/v1/agents/{agent_id}/delete-impact" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

