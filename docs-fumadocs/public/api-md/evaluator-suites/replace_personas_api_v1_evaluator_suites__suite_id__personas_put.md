# PUT /api/v1/evaluator-suites/{suite_id}/personas

Replace Personas

- Operation ID: `replace_personas_api_v1_evaluator_suites__suite_id__personas_put`
- Tags: `Evaluator Suites`
- Auth: Bearer or API Key

## Parameters

- `suite_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X PUT "http://localhost:8000/api/v1/evaluator-suites/{suite_id}/personas" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

