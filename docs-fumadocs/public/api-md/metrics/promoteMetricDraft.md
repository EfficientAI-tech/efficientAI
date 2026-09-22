# POST /api/v1/metrics/{metric_id}/promote

Promote Metric Draft

- Operation ID: `promoteMetricDraft`
- Tags: `Metrics`
- Auth: Bearer or API Key

## Parameters

- `metric_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/metrics/{metric_id}/promote" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

