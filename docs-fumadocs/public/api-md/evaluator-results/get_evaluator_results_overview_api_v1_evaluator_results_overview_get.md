# GET /api/v1/evaluator-results/overview

Get Evaluator Results Overview

- Operation ID: `get_evaluator_results_overview_api_v1_evaluator_results_overview_get`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `agent_id` (query, optional)
  - When set, return suites for this agent
- `suite_id` (query, optional)
  - When set, return scenarios for this suite
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
curl -X GET "http://localhost:8000/api/v1/evaluator-results/overview" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

