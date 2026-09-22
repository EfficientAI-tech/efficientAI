# GET /api/v1/evaluator-results/metric-clusters/eligible-rows

List Evaluator Result Metric Cluster Eligible Rows

- Operation ID: `listEvaluatorResultMetricClusterEligibleRows`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `limit` (query, optional)
- `count_only` (query, optional) `boolean`
- `agent_id` (query, optional)
- `scenario_ids` (query, optional)
- `since` (query, optional)
- `until` (query, optional)
- `suite_id` (query, optional)
- `scenario_id` (query, optional)
- `scope_key` (query, optional)
- `job_id` (query, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/evaluator-results/metric-clusters/eligible-rows" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

