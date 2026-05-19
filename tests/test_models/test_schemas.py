"""Unit tests for Pydantic schema validation logic."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    AgentCreate,
    AgentResponse,
    EvaluationCreate,
    MetricCreate,
    MetricUpdate,
    VoiceBundleResponse,
)


def test_evaluation_create_accepts_allowed_metrics():
    payload = EvaluationCreate(
        audio_id=uuid4(),
        evaluation_type="asr",
        metrics=["wer", "latency"],
    )

    assert payload.metrics == ["wer", "latency"]


def test_evaluation_create_rejects_unknown_metric():
    with pytest.raises(ValidationError, match="Invalid metrics"):
        EvaluationCreate(
            audio_id=uuid4(),
            evaluation_type="asr",
            metrics=["wer", "not_real_metric"],
        )


def test_agent_create_requires_phone_number_for_phone_call():
    with pytest.raises(ValidationError, match="phone_number is required"):
        AgentCreate(
            name="Support Agent",
            description="This description has enough words to satisfy minimum word count requirement.",
            call_type="outbound",
            call_medium="phone_call",
            voice_ai_integration_id=uuid4(),
            voice_ai_agent_id="agent_1",
        )


def test_agent_response_converts_legacy_enum_strings():
    response = AgentResponse(
        id=uuid4(),
        name="Agent",
        phone_number="+1234567890",
        language="ENGLISH",
        description="ok",
        call_type="OUTBOUND",
        call_medium="PHONE_CALL",
        voice_bundle_id=None,
        ai_provider_id=None,
        voice_ai_integration_id=uuid4(),
        voice_ai_agent_id="agent_123",
        provider_prompt=None,
        provider_prompt_synced_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert response.language.value == "en"
    assert response.call_type.value == "outbound"
    assert response.call_medium.value == "phone_call"


def test_voice_bundle_response_converts_provider_enum_from_uppercase_name():
    now = datetime.now(UTC)
    response = VoiceBundleResponse(
        id=uuid4(),
        name="Bundle A",
        description=None,
        bundle_type="stt_llm_tts",
        stt_provider="OPENAI",
        stt_model="gpt-4o-mini-transcribe",
        llm_provider="ANTHROPIC",
        llm_model="claude-3-5-sonnet",
        llm_temperature=0.7,
        llm_max_tokens=256,
        llm_config=None,
        tts_provider="ELEVENLABS",
        tts_model="eleven_multilingual_v2",
        tts_voice="voice_1",
        tts_config=None,
        s2s_provider=None,
        s2s_model=None,
        s2s_config=None,
        extra_metadata=None,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=None,
    )

    assert response.bundle_type.value == "stt_llm_tts"
    assert response.stt_provider.value == "openai"
    assert response.llm_provider.value == "anthropic"
    assert response.tts_provider.value == "elevenlabs"


# ---------------------------------------------------------------------------
# MetricCreate / MetricUpdate: compare_transcripts mutual-exclusion validator
# ---------------------------------------------------------------------------


def test_metric_create_allows_compare_transcripts_on_standalone_metric():
    """The happy path: a standalone metric with compare_transcripts=True
    and no conflicting fields validates cleanly."""
    payload = MetricCreate(
        name="Transcript Fidelity",
        description="Score how well the diarised transcript matches production.",
        metric_type="rating",
        compare_transcripts=True,
    )
    assert payload.compare_transcripts is True
    assert payload.input_columns == []
    assert payload.parent_metric_id is None
    assert payload.selection_mode is None


def test_metric_create_rejects_compare_transcripts_with_input_columns():
    """Comparison + column-input judge are mutually exclusive prompt
    templates — combining them would feed both a transcript pair AND a
    column dictionary to the LLM, with no defined precedence."""
    with pytest.raises(ValidationError, match="column-input"):
        MetricCreate(
            name="Hybrid",
            metric_type="rating",
            compare_transcripts=True,
            input_columns=["customer_intent"],
        )


def test_metric_create_rejects_compare_transcripts_on_child_submetric():
    """v1 keeps comparison metrics standalone — a child sub-metric
    cannot carry the flag because the parent-block prompt template
    doesn't yet know how to render the transcript pair."""
    with pytest.raises(ValidationError, match="standalone"):
        MetricCreate(
            name="Comparison child",
            metric_type="boolean",
            compare_transcripts=True,
            parent_metric_id=uuid4(),
        )


def test_metric_create_rejects_compare_transcripts_on_parent_with_selection_mode():
    """The other half of the standalone rule: a parent category metric
    (selection_mode set) cannot also be a transcript-compare judge."""
    with pytest.raises(ValidationError, match="standalone"):
        MetricCreate(
            name="Comparison parent",
            metric_type="text",
            compare_transcripts=True,
            selection_mode="single_choice",
        )


def test_metric_create_accepts_default_compare_transcripts_false():
    """Backwards compat: omitting the flag preserves today's
    transcript-based judge behavior (input_columns / parent / selection_mode
    remain free to use as before)."""
    payload = MetricCreate(
        name="Old style",
        metric_type="rating",
        input_columns=["customer_intent"],
    )
    assert payload.compare_transcripts is False
    assert payload.input_columns == ["customer_intent"]


def test_metric_update_rejects_compare_transcripts_with_input_columns_in_same_patch():
    """Patch-body level mutual-exclusion: sending the two conflicting
    fields in the same PATCH is rejected up-front so the user gets a
    schema error instead of a route-level 400."""
    with pytest.raises(ValidationError, match="column-input"):
        MetricUpdate(
            compare_transcripts=True,
            input_columns=["agent_response"],
        )


def test_metric_update_rejects_compare_transcripts_with_selection_mode_in_same_patch():
    """Setting selection_mode in the same PATCH that enables
    compare_transcripts contradicts the standalone-only rule."""
    with pytest.raises(ValidationError, match="standalone"):
        MetricUpdate(
            compare_transcripts=True,
            selection_mode="multi_label",
        )


def test_metric_update_allows_compare_transcripts_alone():
    """Standalone PATCH that just sets the flag is fine — cross-state
    validation against the persisted row happens in the update route,
    which has the existing Metric in hand."""
    payload = MetricUpdate(compare_transcripts=True)
    assert payload.compare_transcripts is True
    assert payload.input_columns is None
    assert payload.selection_mode is None


def test_metric_update_allows_clearing_compare_transcripts_while_setting_input_columns():
    """The validator only fires when compare_transcripts is being set
    to True, so the inverse PATCH ("turn the flag off and become a
    column-input judge") is accepted in one round-trip."""
    payload = MetricUpdate(
        compare_transcripts=False,
        input_columns=["customer_intent"],
    )
    assert payload.compare_transcripts is False
    assert payload.input_columns == ["customer_intent"]
