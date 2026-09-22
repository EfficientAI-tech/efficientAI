# GET /api/v1/evaluators/{evaluator_id}

Get Evaluator

- Operation ID: `get_evaluator_api_v1_evaluators__evaluator_id__get`
- Tags: `Evaluators`
- Auth: Bearer or API Key

## Parameters

- `evaluator_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/evaluators/{evaluator_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

