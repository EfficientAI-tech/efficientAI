from uuid import uuid4

from app.services.observability.live_event_emitter import LiveObservabilityEmitter


def test_live_observability_emitter_posts_turns_and_end(db_session, monkeypatch):
    monkeypatch.setattr("app.services.observability.live_event_emitter.settings.OBSERVABILITY_LIVE_INGEST_ENABLED", True)
    org_id = uuid4()
    workspace_id = uuid4()
    emitter = LiveObservabilityEmitter(
        organization_id=org_id,
        workspace_id=workspace_id,
        provider_call_id=f"pipecat-test-{uuid4().hex[:8]}",
        provider_platform="pipecat",
        db_factory=lambda: db_session,
    )

    call_short_id = emitter.start_call()
    assert call_short_id

    emitter.emit_turn("user", "Hello?")
    emitter.emit_turn("assistant", "Hi!", latency={"llm_ms": 300, "tts_ms": 120})
    emitter.end_call(duration_seconds=12.0, trace_id="trace-abc")

    assert emitter.call_short_id == call_short_id
