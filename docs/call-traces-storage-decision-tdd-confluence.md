# Call Traces Storage Decision (S3 WAL + ClickHouse)

## Decision

Replace Postgres WAL (`synthetic_trace_ingest_staging`) and span batch tables with:

1. **S3 batch WAL** — raw OTLP bodies at `{prefix}organizations/{org}/workspaces/{ws}/traces/{uuid}/batches/{seq}.json`
2. **ClickHouse serving store** — `call_traces` (ReplacingMergeTree header) + `trace_observations` (append-only spans)
3. **Redis** — batch sequence (`trace:batch_seq:{uuid}`), live turns (`trace:live:{uuid}`), API key cache on ingest

Postgres remains the **control plane** (orgs, workspaces, API keys, `evaluator_results.synthetic_call_trace_id` as opaque UUID).

## Cutover

1. Deploy ClickHouse + schema (`ensure_schema` on API/worker startup)
2. Deploy API + `worker-traces` with S3-first ingest
3. Run migration `086_drop_pg_trace_span_storage` to drop legacy PG trace tables (no data migration needed on first deploy)

## Ingest failure modes

| Failure | API response |
|---------|----------------|
| S3 PUT fails | 503 (no PG fallback) |
| Celery enqueue after successful PUT | 503 + orphan key (sweeper re-enqueues) |
