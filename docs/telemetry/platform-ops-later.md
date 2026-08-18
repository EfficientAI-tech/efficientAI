# Platform Ops Backlog (Later Rung)

This is intentionally outside Product Observability V1 delivery.

## Deferred scope

- Prometheus metrics hardening for API/media/worker
- Celery trace propagation and queue saturation telemetry
- KEDA/elastic worker autoscaling policies
- PostHog product analytics integration

## Guardrails

- keep product trace shipping independent of platform dashboard rollout
- avoid coupling customer call latency to internal metrics pipelines

## Entry criteria

- V1 call traces are stable in production
- phase 2 webhooks and trace linkage are complete
- load test validates collector and media split behavior
