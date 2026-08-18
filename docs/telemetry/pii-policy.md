# PII Policy for Traces

This policy applies to Product Observability traces and call metadata.

## Never store

- API keys
- auth tokens
- raw credential headers
- secrets from provider integrations

## Transcript handling

- `stt.transcript` can contain user speech and may include PII.
- Default stance: allow transcript attributes for controlled environments.
- For strict environments, disable transcript attribute export and keep only timing/provider metadata.

## Recommended controls

- Add configuration flags to disable transcript payload attributes.
- Truncate long text attributes in UI and API responses.
- Restrict trace query access to workspace-scoped users.

## Logging boundaries

- Do not mirror full transcript text into generic service logs by default.
- Keep detailed transcript payloads in controlled call records or approved stores.

## Compliance posture

- Treat call transcript data as sensitive operational data.
- Preserve tenant isolation using `organization_id` and workspace-level access checks.
