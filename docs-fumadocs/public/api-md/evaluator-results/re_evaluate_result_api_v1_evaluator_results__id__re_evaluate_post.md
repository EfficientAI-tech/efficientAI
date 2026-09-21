# POST /api/v1/evaluator-results/{id}/re-evaluate

Re Evaluate Result

- Operation ID: `re_evaluate_result_api_v1_evaluator_results__id__re_evaluate_post`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/evaluator-results/{id}/re-evaluate" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

