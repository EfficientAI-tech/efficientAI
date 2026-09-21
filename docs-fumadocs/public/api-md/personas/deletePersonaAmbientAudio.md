# DELETE /api/v1/personas/{persona_id}/ambient-audio

Delete Persona Ambient Audio

- Operation ID: `deletePersonaAmbientAudio`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `persona_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/personas/{persona_id}/ambient-audio" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

