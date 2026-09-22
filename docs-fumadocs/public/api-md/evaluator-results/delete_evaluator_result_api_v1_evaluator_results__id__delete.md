# DELETE /api/v1/evaluator-results/{id}

Delete Evaluator Result

- Operation ID: `delete_evaluator_result_api_v1_evaluator_results__id__delete`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `204` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/evaluator-results/{id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

