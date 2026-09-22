# DELETE /api/v1/voicebundles/{voicebundle_id}

Delete Voicebundle

- Operation ID: `deleteVoiceBundle`
- Tags: `Voice Bundles`
- Auth: Bearer or API Key

## Parameters

- `voicebundle_id` (path, required) `string`
- `force` (query, optional) `boolean`
  - Force delete with all dependent records
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/voicebundles/{voicebundle_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

