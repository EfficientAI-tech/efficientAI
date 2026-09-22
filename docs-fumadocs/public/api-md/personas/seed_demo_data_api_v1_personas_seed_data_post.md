# POST /api/v1/personas/seed-data

Seed Demo Data

- Operation ID: `seed_demo_data_api_v1_personas_seed_data_post`
- Tags: `Personas`
- Auth: Bearer or API Key

## Parameters

- `X-Workspace-Id` (header, optional)
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `201` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X POST "http://localhost:8000/api/v1/personas/seed-data" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

