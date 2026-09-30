# Fumadocs archive (Confluence staging)

Public docs live in `docs-fumadocs/`. While that tree is locked for parallel edits, **canonical draft copies** for the next Fumadocs publish live here and on Confluence under **ETD → Fumadocs archive**.

| Archive file | Future Fumadocs path | Confluence page (when published) |
| --- | --- | --- |
| `monitoring/call-traces/01-overview.md` | `monitoring/call-traces/index.mdx` | Call Traces — overview |
| `monitoring/call-traces/02-latency-metrics.md` | `monitoring/call-traces/latency-metrics.mdx` | Latency metrics |
| `monitoring/call-traces/03-architecture-and-scaling.md` | `monitoring/call-traces/architecture.mdx` | Architecture & scaling |
| `monitoring/call-traces/04-pipecat-otlp-integration.md` (incl. `pipecat-agent` lab) | `monitoring/call-traces/pipecat-integration.mdx` | Pipecat & OTLP integration |

**Content baseline:** `otel-traces` branch — ClickHouse span storage, S3 WAL, `worker-traces`, deferred ingest (HTTP **202**). Postgres is control-plane only (`evaluator_results.synthetic_call_trace_id`); migration **092** removes legacy PG trace tables.

**Copy to Fumadocs:** Convert headings to MDX frontmatter, replace internal links with `/docs/monitoring/call-traces/...`, restore Fumadocs admonitions (`:::info` etc.).
