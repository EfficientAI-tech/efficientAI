# Scale Architecture One-Pager (~10M calls/day)

## Baseline model

- Media plane handles live WebSockets and in-process span creation.
- API plane handles CRUD, call metadata, and trace query proxy.
- Worker plane handles async batch tasks (imports/evals), not real-time media.
- OTel Collector fleet handles telemetry ingestion buffering, retries, and fan-out.

## Flow

```text
Client/WebRTC/Telephony
  -> media replicas (SERVICE_MODE=media)
  -> spans (non-blocking, batch processor)
  -> OTel Collector fleet
  -> EfficientAI trace store (and optional Tempo)

call-end metadata -> API/DB (single write per call)
```

## Operational rules

- No per-span Postgres writes.
- Use `BatchSpanProcessor`; never block media thread on exporter.
- Apply sampling by tier/org (for example 10-20% default, 100% premium).
- Prefer dropping spans over dropping calls under pressure.

## Capacity strategy

- Scale media replicas on concurrent sessions.
- Scale collectors on span ingress throughput.
- Keep API isolated from media spikes.

## Quotas and fairness

- Per-org call and trace budget controls.
- Backpressure and shed-load behavior should be explicit and observable.
- Local/OSS config hooks:
  - `OBSERVABILITY_TRACING_SAMPLE_RATE` for baseline sampling.
  - `OBSERVABILITY_TRACE_QUOTA_PER_ORG_PER_DAY` to emit quota warnings without blocking calls.

## Suggested tier defaults

- Default orgs: sample 10-20% of traces.
- Premium orgs: sample 100% of traces.
- Under sustained pressure, drop spans before impacting live call handling.
