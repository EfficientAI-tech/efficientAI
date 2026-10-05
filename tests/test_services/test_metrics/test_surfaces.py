from app.services.metrics.surfaces import (
    SURFACE_CHAT_AGENT,
    SURFACE_VOICE_AGENT,
    metric_enabled_for_eval_surface,
    metric_eval_surface_for_call_medium,
)


def test_metric_eval_surface_for_call_medium():
    assert metric_eval_surface_for_call_medium("chat") == SURFACE_CHAT_AGENT
    assert metric_eval_surface_for_call_medium("phone_call") == SURFACE_VOICE_AGENT
    assert metric_eval_surface_for_call_medium(None) == SURFACE_VOICE_AGENT


def test_metric_enabled_for_eval_surface_legacy_defaults_both_agent_mediums():
    assert metric_enabled_for_eval_surface([], SURFACE_VOICE_AGENT)
    assert metric_enabled_for_eval_surface([], SURFACE_CHAT_AGENT)


def test_metric_enabled_for_eval_surface_explicit_lists():
    both = [SURFACE_VOICE_AGENT, SURFACE_CHAT_AGENT]
    assert metric_enabled_for_eval_surface(both, SURFACE_CHAT_AGENT)
    assert metric_enabled_for_eval_surface(both, SURFACE_VOICE_AGENT)
    assert not metric_enabled_for_eval_surface([SURFACE_VOICE_AGENT], SURFACE_CHAT_AGENT)
