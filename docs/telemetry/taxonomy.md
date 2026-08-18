# Taxonomy: Product vs Platform Observability

EfficientAI has two observability layers that share telemetry primitives but solve different problems.

## Product Observability (this epic)

Primary user: customer teams and agent builders.

Questions answered:

- Which part of a call was slow (STT, LLM, TTS)?
- Why did this specific call fail?
- What was the trace for this call ID?

Primary entities:

- `CallRecording`
- `trace_id`
- call detail UI
- trace waterfall UI

Signals:

- traces and call metadata
- call-level aggregate stats

### Provider trace namespaces

To avoid span naming conflicts between EfficientAI-native traces and provider traces:

- EfficientAI voice-bundle traces retain canonical names:
  - `conversation`, `turn`, `stt`, `llm`, `tts`, `tool_call`
- Provider traces keep provider-native names:
  - ElevenLabs examples: `elevenlabs.conversation`, `elevenlabs.recv.user_transcript`, `elevenlabs.recv.agent_response`
- Provider-derived synthetic rows (if added) must stay namespaced:
  - `elevenlabs.metric.asr`, `elevenlabs.metric.llm`, `elevenlabs.metric.tts`

Every normalized provider span should include `attributes.trace.provider` to make source-aware UI rendering deterministic.

## Platform Observability (later epic)

Primary user: platform and SRE operators.

Questions answered:

- Are API/media/worker services healthy?
- Is queue depth growing?
- Are collectors dropping spans?

Primary entities:

- service-level metrics and logs
- infra dashboards and alerts

Signals:

- Prometheus metrics
- Loki logs
- collector/process health

## Shared correlation spine

Both layers should preserve these keys end-to-end:

- `organization_id`
- `workspace_id`
- `agent_id`
- `trace_id`
- `provider_call_id`
