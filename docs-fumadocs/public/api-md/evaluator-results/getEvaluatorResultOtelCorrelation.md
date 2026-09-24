# GET /api/v1/evaluator-results/{id}/otel-correlation

OTLP endpoint and correlation env for Pipecat tracing

- Operation ID: `getEvaluatorResultOtelCorrelation`
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
curl -X GET "http://localhost:8000/api/v1/evaluator-results/{id}/otel-correlation" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

