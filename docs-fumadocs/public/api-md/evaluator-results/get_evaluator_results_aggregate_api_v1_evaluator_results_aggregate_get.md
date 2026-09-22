# GET /api/v1/evaluator-results/aggregate

Get Evaluator Results Aggregate

- Operation ID: `get_evaluator_results_aggregate_api_v1_evaluator_results_aggregate_get`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `suite_id` (query, optional)
- `agent_id` (query, optional)
- `scenario_id` (query, optional)
- `since` (query, optional)
- `until` (query, optional)
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/evaluator-results/aggregate" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

