# DELETE /api/v1/workspaces/{workspace_id}

Delete Workspace

- Operation ID: `delete_workspace_api_v1_workspaces__workspace_id__delete`
- Tags: `Workspaces`
- Auth: Bearer or API Key

## Parameters

- `workspace_id` (path, required) `string`
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)

## Responses

- `204` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X DELETE "http://localhost:8000/api/v1/workspaces/{workspace_id}" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

