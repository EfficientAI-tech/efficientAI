# GET /api/v1/observability/traces/results/{evaluator_result_id}

Get Trace For Evaluator Result

- Operation ID: `getObservabilityTraceForEvaluatorResult`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `evaluator_result_id` (path, required) `string`
- `include_spans` (query, optional) `boolean`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/observability/traces/results/{evaluator_result_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

