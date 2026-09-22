# DELETE /api/v1/call-import-schemas/{schema_id}

Delete Call Import Schema

- Operation ID: `deleteCallImportSchema`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `schema_id` (path, required) `string`
- `force` (query, optional) `boolean`
  - When true, detach this schema from any CallImport batches that reference it (sets ``call_imports.schema_id = NULL``) before deleting the schema row. Use this to drop a schema whose batches you want to keep — already-imported batches keep working via their snapshotted ``parameter_mapping``, while staged-but-not-yet-imported batches will need a new schema picked before they can be imported.
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `204` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/call-import-schemas/{schema_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

