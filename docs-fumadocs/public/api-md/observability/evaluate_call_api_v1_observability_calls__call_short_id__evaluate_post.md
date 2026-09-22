# POST /api/v1/observability/calls/{call_short_id}/evaluate

Evaluate Call

- Operation ID: `evaluate_call_api_v1_observability_calls__call_short_id__evaluate_post`
- Tags: `Observability`
- Auth: Bearer or API Key

## Parameters

- `call_short_id` (path, required) `string`
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
curl -X POST "http://localhost:8000/api/v1/observability/calls/{call_short_id}/evaluate" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

