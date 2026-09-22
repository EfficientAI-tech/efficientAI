# POST /api/v1/scenarios

Create Scenario

- Operation ID: `create_scenario_api_v1_scenarios_post`
- Tags: `Scenarios`
- Auth: Bearer or API Key

## Parameters

- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `201` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/scenarios" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

