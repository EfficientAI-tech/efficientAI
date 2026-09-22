# DELETE /api/v1/evaluators/{evaluator_id}

Delete Evaluator

- Operation ID: `delete_evaluator_api_v1_evaluators__evaluator_id__delete`
- Tags: `Evaluators`
- Auth: Bearer or API Key

## Parameters

- `evaluator_id` (path, required) `string`
- `force` (query, optional) `boolean`
  - Deprecated: evaluator deletion keeps dependent results
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/evaluators/{evaluator_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

