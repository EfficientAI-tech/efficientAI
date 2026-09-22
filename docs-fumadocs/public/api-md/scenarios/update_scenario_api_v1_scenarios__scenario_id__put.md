# PUT /api/v1/scenarios/{scenario_id}

Update Scenario

- Operation ID: `update_scenario_api_v1_scenarios__scenario_id__put`
- Tags: `Scenarios`
- Auth: Bearer or API Key

## Parameters

- `scenario_id` (path, required) `string`
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
curl -X PUT "http://localhost:8000/api/v1/scenarios/{scenario_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

