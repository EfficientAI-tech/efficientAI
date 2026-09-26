# Call traces — workspace correlation (E2E)

## Flow

1. **Session** — `POST /api/v1/observability/traces/sessions` with `X-Workspace-Id` + API key. Creates trace header in that workspace (`call_short_id` minted).
2. **OTLP export** — `POST /api/v1/observability/traces` must use the **same** workspace:
   - `X-Workspace-Id` on the HTTP request (SDK sends this from `EFFICIENTAI_WORKSPACE_ID`).
   - `X-EfficientAI-Call-Short-Id` links batches to the session row.
   - Span attributes `efficientai.workspace_id` / `efficientai.call_short_id` (backup).
3. **Worker** — WAL batches under `traces/organizations/<org>/workspaces/<ws>/traces/<trace-id>/`.
4. **Close** — `POST .../sessions/{call_short_id}/close` with same `X-Workspace-Id`.

## Pitfall (fixed)

API-key OTLP requests **without** `X-Workspace-Id` used to resolve to the org **default** workspace while sessions used `EFFICIENTAI_WORKSPACE_ID` → empty trace in demo workspace, spans in default.

**Client:** `efficientai[otel]` adds `X-Workspace-Id` on OTLP export.  
**Server:** `resolve_otlp_ingest_workspace_id` re-resolves workspace from `call_short_id` / span attrs when ingest would otherwise use the wrong workspace.

## Bot `.env`

```env
EFFICIENTAI_WORKSPACE_ID=<target-workspace-uuid>
EFFICIENTAI_OTLP_ENDPOINT=https://<host>/api/v1/observability/traces
```

Restart the bot after changes. If using `load_dotenv(override=True)`, **`.env` wins** over shell `export`.

## Verify

- UI **Calls** in the **same** workspace as `EFFICIENTAI_WORKSPACE_ID`.
- One call → one row with turns/spans after worker processes batches.
