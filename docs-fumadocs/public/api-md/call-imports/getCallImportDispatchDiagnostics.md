# GET /api/v1/call-imports/dispatch-diagnostics

Get Call Import Dispatch Diagnostics

- Operation ID: `getCallImportDispatchDiagnostics`
- Tags: `Call Imports`
- Auth: Bearer or API Key

## Parameters

- `workspace_id` (query, optional)
  - Optional workspace filter. When omitted, returns every workspace in the organization with active eval dispatch state.
- `include_idle_workspaces` (query, optional) `boolean`
  - When true, include org workspaces with zero pending rows and zero in-flight slots.
- `Authorization` (header, optional)
- `X-API-Key` (header, optional)
- `X-EFFICIENTAI-API-KEY` (header, optional)
- `X-Workspace-Id` (header, optional)

## Responses

- `200` - Successful Response
- `422` - Validation Error

## cURL

```bash
curl -X GET "http://localhost:8000/api/v1/call-imports/dispatch-diagnostics" \
  -H "Authorization: Bearer <token>" \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json"
```

