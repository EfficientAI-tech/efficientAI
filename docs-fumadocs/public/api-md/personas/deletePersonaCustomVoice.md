# DELETE /api/v1/personas/custom-voices/{custom_voice_id}

Delete Custom Voice

- Operation ID: `deletePersonaCustomVoice`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `custom_voice_id` (path, required) `string`
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/personas/custom-voices/{custom_voice_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

