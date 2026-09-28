# GET /api/v1/observability/traces/setup

Get Otlp Setup

- Operation ID: `getObservabilityTracesSetup`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `Authorization` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/observability/traces/setup" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

