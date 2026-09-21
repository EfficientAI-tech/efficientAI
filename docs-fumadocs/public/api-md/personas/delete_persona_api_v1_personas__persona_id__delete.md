# DELETE /api/v1/personas/{persona_id}

Delete Persona

- Operation ID: `delete_persona_api_v1_personas__persona_id__delete`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `persona_id` (path, required) `string`
- `force` (query, optional) `boolean`
  - Force delete with all dependent records
- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/personas/{persona_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

