# POST /api/v1/metrics/generate

Generate Metric

- Operation ID: `generate_metric_api_v1_metrics_generate_post`
- Tags: `Metrics`
- Auth: Bearer or API Key

## Parameters

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
curl -X POST "http://localhost:8000/api/v1/metrics/generate" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

