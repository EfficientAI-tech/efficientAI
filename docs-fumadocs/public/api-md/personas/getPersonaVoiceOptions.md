# GET /api/v1/personas/voice-options

Get Voice Options

- Operation ID: `getPersonaVoiceOptions`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `provider` (query, optional)
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/personas/voice-options" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

