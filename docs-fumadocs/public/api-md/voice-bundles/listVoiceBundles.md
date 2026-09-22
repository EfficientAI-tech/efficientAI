# GET /api/v1/voicebundles

List Voicebundles

- Operation ID: `listVoiceBundles`
- Tags: `Voice Bundles`
- Auth: Bearer or API Key

## Parameters

- `skip` (query, optional) `integer`
- `limit` (query, optional) `integer`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/voicebundles" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

