# GET /api/v1/evaluator-results/{id}/audio

Stream Evaluator Result Audio

- Operation ID: `stream_evaluator_result_audio_api_v1_evaluator_results__id__audio_get`
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
curl -X GET "http://localhost:8000/api/v1/evaluator-results/{id}/audio" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

