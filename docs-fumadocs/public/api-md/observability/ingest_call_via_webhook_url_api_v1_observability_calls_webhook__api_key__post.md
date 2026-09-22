# POST /api/v1/observability/calls/webhook/{api_key}

Ingest Call Via Webhook Url

- Operation ID: `ingest_call_via_webhook_url_api_v1_observability_calls_webhook__api_key__post`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `api_key` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `201` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/observability/calls/webhook/{api_key}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

