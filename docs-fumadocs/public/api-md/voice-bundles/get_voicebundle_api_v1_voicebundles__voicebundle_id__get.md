# GET /api/v1/voicebundles/{voicebundle_id}

Get Voicebundle

- Operation ID: `get_voicebundle_api_v1_voicebundles__voicebundle_id__get`
- Tags: `Voice Bundles`
- Auth: Bearer or API Key

## Parameters

- `voicebundle_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/voicebundles/{voicebundle_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

