# DELETE /api/v1/scenarios/{scenario_id}

Delete Scenario

- Operation ID: `delete_scenario_api_v1_scenarios__scenario_id__delete`
- Tags: `Scenarios`
- Auth: Bearer or API Key

## Parameters

- `scenario_id` (path, required) `string`
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
curl -X DELETE "http://localhost:8000/api/v1/scenarios/{scenario_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

