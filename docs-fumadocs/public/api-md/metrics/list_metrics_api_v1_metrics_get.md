# GET /api/v1/metrics

List Metrics

- Operation ID: `list_metrics_api_v1_metrics_get`
- Tags: `Metrics`
- Auth: Bearer or API Key

## Parameters

- `surface` (query, optional)
- `include_drafts` (query, optional) `boolean`
  - When true, include draft metrics (Studio-only) in the listing.
- `drafts_only` (query, optional) `boolean`
  - When true, return only draft metrics.
- `enabled_only` (query, optional) `boolean`
  - When true, return only metrics enabled in the active workspace. Category parents are included when at least one child is enabled.
- `include_children` (query, optional) `boolean`
  - When true (default), children are nested under their parent and not returned as top-level rows. When false, the response is a flat list of every metric (parents + standalone + orphaned children).
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/metrics" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

