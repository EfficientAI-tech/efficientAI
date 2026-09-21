# GET /api/v1/agents/check-phone-assignment

Check Phone Assignment

- Operation ID: `check_phone_assignment_api_v1_agents_check_phone_assignment_get`
- Tags: `Agents`
- Auth: Bearer or API Key

## Parameters

- `phone_number` (query, optional)
- `telephony_phone_number_id` (query, optional)
- `exclude_agent_id` (query, optional)
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/agents/check-phone-assignment" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

