# GET /api/v1/observability/traces/ingest/{staging_id}

Get Trace Ingest Staging Status

- Operation ID: `getObservabilityTraceIngestStaging`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `staging_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/observability/traces/ingest/{staging_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

