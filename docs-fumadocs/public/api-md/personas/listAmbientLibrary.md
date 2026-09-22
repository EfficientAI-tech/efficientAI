# GET /api/v1/personas/ambient-library

List Ambient Library

- Operation ID: `listAmbientLibrary`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/personas/ambient-library" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

