# GET /api/v1/evaluator-suites/{suite_id}

Get Suite

- Operation ID: `get_suite_api_v1_evaluator_suites__suite_id__get`
- Tags: `Evaluator Suites`
- Auth: Bearer or API Key

## Parameters

- `suite_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/evaluator-suites/{suite_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

