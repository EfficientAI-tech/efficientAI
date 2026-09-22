# POST /api/v1/personas/{persona_id}/clone

Clone Persona

- Operation ID: `clone_persona_api_v1_personas__persona_id__clone_post`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `persona_id` (path, required) `string`
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
curl -X POST "http://localhost:8000/api/v1/personas/{persona_id}/clone" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

