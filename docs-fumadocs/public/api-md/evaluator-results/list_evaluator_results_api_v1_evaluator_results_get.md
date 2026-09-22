# GET /api/v1/evaluator-results

List Evaluator Results

- Operation ID: `list_evaluator_results_api_v1_evaluator_results_get`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `skip` (query, optional) `integer`
- `limit` (query, optional) `integer`
- `evaluator_id` (query, optional)
- `agent_id` (query, optional)
  - Filter by associated agent UUID
- `suite_id` (query, optional)
  - Filter by evaluator suite UUID
- `scenario_id` (query, optional)
  - Filter by scenario UUID
- `status` (query, optional)
  - Filter by display status: completed, failed, in_progress
- `since` (query, optional)
- `until` (query, optional)
- `unassigned_only` (query, optional)
  - When true, only legacy/manual results without a suite
- `playground` (query, optional)
  - If true, only return playground test results (evaluator_id is NULL). If false, exclude playground results. If not provided, exclude playground results by default.
- `test_agents_only` (query, optional)
  - If true, only return Test Agent results (no provider_platform). If false, include all playground results.
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/evaluator-results" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

