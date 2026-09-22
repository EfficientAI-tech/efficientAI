# POST /api/v1/personas/generate-prompt

Generate Persona Prompt

- Operation ID: `generatePersonaPrompt`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Request Body

See schema in API reference UI.

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/personas/generate-prompt" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

