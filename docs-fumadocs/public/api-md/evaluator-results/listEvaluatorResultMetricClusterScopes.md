# GET /api/v1/evaluator-results/metric-clusters/scopes

List Evaluator Result Metric Cluster Scopes

- Operation ID: `listEvaluatorResultMetricClusterScopes`
- Tags: `Evaluator Results`
- Auth: Bearer or API Key

## Parameters

- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/evaluator-results/metric-clusters/scopes" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

