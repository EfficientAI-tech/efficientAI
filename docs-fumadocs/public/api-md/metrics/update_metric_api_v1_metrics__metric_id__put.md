# PUT /api/v1/metrics/{metric_id}

Update Metric

- Operation ID: `update_metric_api_v1_metrics__metric_id__put`
- Tags: `Metrics`
- Auth: Bearer or API Key

## Parameters

- `metric_id` (path, required) `string`
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
curl -X PUT "http://localhost:8000/api/v1/metrics/{metric_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

