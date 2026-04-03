"""Shared fixtures for API route tests."""

from uuid import uuid4

import pytest

from app.models.database import (
    Agent,
    Alert,
    APIKey,
    AIProvider,
    AudioFile,
    CallRecording,
    CallRecordingSource,
    CallRecordingStatus,
    ConversationEvaluation,
    PromptOptimizationCandidate,
    PromptOptimizationRun,
    Evaluation,
    EvaluationResult,
    Evaluator,
    EvaluatorResult,
    Integration,
    ManualTranscription,
    Metric,
    OrganizationMember,
    Organization,
    Persona,
    Scenario,
    TestAgentConversation,
    User,
    VoiceBundle,
)
from app.models.enums import EvaluationStatus, IntegrationPlatform, MetricTrigger, MetricType, RoleEnum


@pytest.fixture
def seed_org(db_session, org_id):
    org = Organization(id=org_id, name="Test Org")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def make_audio(db_session, org_id, seed_org):
    def _make_audio(**overrides):
        audio = AudioFile(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            filename=overrides.get("filename", "sample.wav"),
            file_path=overrides.get("file_path", "/tmp/sample.wav"),
            file_size=overrides.get("file_size", 1024),
            duration=overrides.get("duration", 2.5),
            sample_rate=overrides.get("sample_rate", 16000),
            channels=overrides.get("channels", 1),
            format=overrides.get("format", "wav"),
        )
        db_session.add(audio)
        db_session.commit()
        db_session.refresh(audio)
        return audio

    return _make_audio


@pytest.fixture
def make_evaluation(db_session, org_id, seed_org, make_audio):
    def _make_evaluation(**overrides):
        audio = overrides.get("audio") or make_audio()
        evaluation = Evaluation(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            audio_id=audio.id,
            reference_text=overrides.get("reference_text", "hello world"),
            evaluation_type=overrides.get("evaluation_type", "asr"),
            model_name=overrides.get("model_name", "base"),
            status=overrides.get("status", EvaluationStatus.PENDING.value),
            metrics_requested=overrides.get("metrics_requested", ["wer", "latency"]),
        )
        db_session.add(evaluation)
        db_session.commit()
        db_session.refresh(evaluation)
        return evaluation

    return _make_evaluation


@pytest.fixture
def make_evaluation_result(db_session):
    def _make_result(evaluation, **overrides):
        result = EvaluationResult(
            id=overrides.get("id", uuid4()),
            evaluation_id=evaluation.id,
            transcript=overrides.get("transcript", "hello world"),
            metrics=overrides.get("metrics", {"wer": 0.1, "latency_ms": 300}),
            raw_output=overrides.get("raw_output", {}),
            processing_time=overrides.get("processing_time", 0.3),
            model_used=overrides.get("model_used", "base"),
        )
        db_session.add(result)
        db_session.commit()
        db_session.refresh(result)
        return result

    return _make_result


@pytest.fixture
def make_integration(db_session, org_id, seed_org):
    def _make_integration(**overrides):
        integration = Integration(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            platform=overrides.get("platform", IntegrationPlatform.RETELL.value),
            name=overrides.get("name", "Retell Integration"),
            api_key=overrides.get("api_key", "enc-key"),
            public_key=overrides.get("public_key"),
            is_active=overrides.get("is_active", True),
        )
        db_session.add(integration)
        db_session.commit()
        db_session.refresh(integration)
        return integration

    return _make_integration


@pytest.fixture
def make_agent(db_session, org_id, seed_org, make_integration):
    def _make_agent(**overrides):
        integration = overrides.get("integration") or make_integration()
        agent = Agent(
            id=overrides.get("id", uuid4()),
            agent_id=overrides.get("agent_id", "123456"),
            organization_id=org_id,
            name=overrides.get("name", "Agent A"),
            phone_number=overrides.get("phone_number", "+1234567890"),
            language=overrides.get("language", "en"),
            description=overrides.get("description", "Agent description"),
            call_type=overrides.get("call_type", "outbound"),
            call_medium=overrides.get("call_medium", "phone_call"),
            voice_bundle_id=overrides.get("voice_bundle_id"),
            ai_provider_id=overrides.get("ai_provider_id"),
            voice_ai_integration_id=overrides.get("voice_ai_integration_id", integration.id),
            voice_ai_agent_id=overrides.get("voice_ai_agent_id", "voice-agent-1"),
        )
        db_session.add(agent)
        db_session.commit()
        db_session.refresh(agent)
        return agent

    return _make_agent


@pytest.fixture
def make_persona(db_session, org_id, seed_org):
    def _make_persona(**overrides):
        persona = Persona(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            name=overrides.get("name", "Persona A"),
            gender=overrides.get("gender", "neutral"),
            tts_provider=overrides.get("tts_provider"),
            tts_voice_id=overrides.get("tts_voice_id"),
            tts_voice_name=overrides.get("tts_voice_name"),
            is_custom=overrides.get("is_custom", False),
        )
        db_session.add(persona)
        db_session.commit()
        db_session.refresh(persona)
        return persona

    return _make_persona


@pytest.fixture
def make_scenario(db_session, org_id, seed_org):
    def _make_scenario(**overrides):
        scenario = Scenario(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            agent_id=overrides.get("agent_id"),
            name=overrides.get("name", "Scenario A"),
            description=overrides.get("description", "Scenario description"),
            required_info=overrides.get("required_info", {}),
        )
        db_session.add(scenario)
        db_session.commit()
        db_session.refresh(scenario)
        return scenario

    return _make_scenario


@pytest.fixture
def make_evaluator(db_session, org_id, seed_org):
    def _make_evaluator(**overrides):
        evaluator = Evaluator(
            id=overrides.get("id", uuid4()),
            evaluator_id=overrides.get("evaluator_id", "654321"),
            organization_id=org_id,
            name=overrides.get("name", "Evaluator A"),
            agent_id=overrides.get("agent_id"),
            persona_id=overrides.get("persona_id"),
            scenario_id=overrides.get("scenario_id"),
            custom_prompt=overrides.get("custom_prompt"),
            llm_provider=overrides.get("llm_provider"),
            llm_model=overrides.get("llm_model"),
            tags=overrides.get("tags"),
        )
        db_session.add(evaluator)
        db_session.commit()
        db_session.refresh(evaluator)
        return evaluator

    return _make_evaluator


@pytest.fixture
def make_user(db_session):
    def _make_user(**overrides):
        user = User(
            id=overrides.get("id", uuid4()),
            email=overrides.get("email", f"user-{uuid4()}@example.com"),
            name=overrides.get("name", "Test User"),
            first_name=overrides.get("first_name"),
            last_name=overrides.get("last_name"),
            password_hash=overrides.get("password_hash"),
            is_active=overrides.get("is_active", True),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make_user


@pytest.fixture
def user_context(db_session, org_id, api_key, seed_org, make_user):
    """Seed user + org membership + API key for IAM/settings tests."""
    user = make_user(email="owner@example.com", name="Org Owner")
    membership = OrganizationMember(
        id=uuid4(),
        organization_id=org_id,
        user_id=user.id,
        role=RoleEnum.ADMIN.value,
    )
    key = APIKey(
        id=uuid4(),
        key=api_key,
        name="Owner API Key",
        organization_id=org_id,
        user_id=user.id,
        is_active=True,
    )
    db_session.add(membership)
    db_session.add(key)
    db_session.commit()
    return {"user": user, "membership": membership, "api_key_record": key}


@pytest.fixture
def make_ai_provider(db_session, org_id, seed_org):
    def _make_ai_provider(**overrides):
        provider = AIProvider(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            provider=overrides.get("provider", "openai"),
            api_key=overrides.get("api_key", "enc-api-key"),
            name=overrides.get("name", "OpenAI Key"),
            is_active=overrides.get("is_active", True),
        )
        db_session.add(provider)
        db_session.commit()
        db_session.refresh(provider)
        return provider

    return _make_ai_provider


@pytest.fixture
def make_metric(db_session, org_id, seed_org):
    def _make_metric(**overrides):
        metric = Metric(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            name=overrides.get("name", "Professionalism"),
            description=overrides.get("description", "Professional tone"),
            metric_type=overrides.get("metric_type", MetricType.RATING.value),
            trigger=overrides.get("trigger", MetricTrigger.ALWAYS.value),
            enabled=overrides.get("enabled", True),
            is_default=overrides.get("is_default", False),
        )
        db_session.add(metric)
        db_session.commit()
        db_session.refresh(metric)
        return metric

    return _make_metric


@pytest.fixture
def make_evaluator_result(db_session, org_id, seed_org):
    def _make_evaluator_result(**overrides):
        evaluator_result = EvaluatorResult(
            id=overrides.get("id", uuid4()),
            result_id=overrides.get("result_id", "112233"),
            organization_id=org_id,
            evaluator_id=overrides.get("evaluator_id"),
            agent_id=overrides.get("agent_id"),
            persona_id=overrides.get("persona_id"),
            scenario_id=overrides.get("scenario_id"),
            name=overrides.get("name", "Result One"),
            duration_seconds=overrides.get("duration_seconds", 10.5),
            status=overrides.get("status", "completed"),
            audio_s3_key=overrides.get("audio_s3_key", "audio/key.mp3"),
            transcription=overrides.get("transcription", "hello there"),
            speaker_segments=overrides.get("speaker_segments"),
            metric_scores=overrides.get("metric_scores"),
            celery_task_id=overrides.get("celery_task_id"),
            error_message=overrides.get("error_message"),
            provider_platform=overrides.get("provider_platform"),
            call_data=overrides.get("call_data"),
        )
        db_session.add(evaluator_result)
        db_session.commit()
        db_session.refresh(evaluator_result)
        return evaluator_result

    return _make_evaluator_result


@pytest.fixture
def make_voice_bundle(db_session, org_id, seed_org):
    def _make_voice_bundle(**overrides):
        bundle = VoiceBundle(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            name=overrides.get("name", "Voice Bundle A"),
            description=overrides.get("description", "Bundle for testing"),
            bundle_type=overrides.get("bundle_type", "stt_llm_tts"),
            stt_provider=overrides.get("stt_provider", "openai"),
            stt_model=overrides.get("stt_model", "whisper-1"),
            llm_provider=overrides.get("llm_provider", "openai"),
            llm_model=overrides.get("llm_model", "gpt-4o-mini"),
            tts_provider=overrides.get("tts_provider", "openai"),
            tts_model=overrides.get("tts_model", "gpt-4o-mini-tts"),
            is_active=overrides.get("is_active", True),
        )
        db_session.add(bundle)
        db_session.commit()
        db_session.refresh(bundle)
        return bundle

    return _make_voice_bundle


@pytest.fixture
def make_test_agent_conversation(db_session, org_id, seed_org):
    def _make_test_agent_conversation(**overrides):
        conversation = TestAgentConversation(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            agent_id=overrides["agent_id"],
            persona_id=overrides["persona_id"],
            scenario_id=overrides["scenario_id"],
            voice_bundle_id=overrides.get("voice_bundle_id"),
            status=overrides.get("status", "completed"),
            live_transcription=overrides.get("live_transcription"),
            full_transcript=overrides.get("full_transcript"),
            conversation_metadata=overrides.get("conversation_metadata"),
        )
        db_session.add(conversation)
        db_session.commit()
        db_session.refresh(conversation)
        return conversation

    return _make_test_agent_conversation


@pytest.fixture
def make_manual_transcription(db_session, org_id, seed_org):
    def _make_manual_transcription(**overrides):
        transcription = ManualTranscription(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            name=overrides.get("name", "Manual Transcript A"),
            audio_file_key=overrides.get("audio_file_key", "organizations/test/audio-1.wav"),
            transcript=overrides.get("transcript", "Hello this is a transcript."),
            speaker_segments=overrides.get("speaker_segments"),
            stt_model=overrides.get("stt_model", "whisper-1"),
            stt_provider=overrides.get("stt_provider", "openai"),
            language=overrides.get("language", "en"),
            processing_time=overrides.get("processing_time", 0.2),
            raw_output=overrides.get("raw_output"),
        )
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
        return transcription

    return _make_manual_transcription


@pytest.fixture
def make_conversation_evaluation(db_session, org_id, seed_org):
    def _make_conversation_evaluation(**overrides):
        evaluation = ConversationEvaluation(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            transcription_id=overrides["transcription_id"],
            agent_id=overrides["agent_id"],
            objective_achieved=overrides.get("objective_achieved", True),
            objective_achieved_reason=overrides.get("objective_achieved_reason", "Objective completed"),
            additional_metrics=overrides.get("additional_metrics", {"overall_quality": 0.8}),
            overall_score=overrides.get("overall_score", 0.8),
            llm_provider=overrides.get("llm_provider", "openai"),
            llm_model=overrides.get("llm_model", "gpt-4o-mini"),
            llm_response=overrides.get("llm_response", {"text": "ok"}),
        )
        db_session.add(evaluation)
        db_session.commit()
        db_session.refresh(evaluation)
        return evaluation

    return _make_conversation_evaluation


@pytest.fixture
def make_alert(db_session, org_id, seed_org):
    def _make_alert(**overrides):
        alert = Alert(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            name=overrides.get("name", "High Call Volume"),
            description=overrides.get("description", "Call spikes"),
            metric_type=overrides.get("metric_type", "number_of_calls"),
            aggregation=overrides.get("aggregation", "sum"),
            operator=overrides.get("operator", ">"),
            threshold_value=overrides.get("threshold_value", 100.0),
            time_window_minutes=overrides.get("time_window_minutes", 60),
            agent_ids=overrides.get("agent_ids"),
            notify_frequency=overrides.get("notify_frequency", "immediate"),
            notify_emails=overrides.get("notify_emails"),
            notify_webhooks=overrides.get("notify_webhooks"),
            status=overrides.get("status", "active"),
        )
        db_session.add(alert)
        db_session.commit()
        db_session.refresh(alert)
        return alert

    return _make_alert


@pytest.fixture
def make_call_recording(db_session, org_id, seed_org):
    def _make_call_recording(**overrides):
        call_recording = CallRecording(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            call_short_id=overrides.get("call_short_id", "123456"),
            status=overrides.get("status", CallRecordingStatus.PENDING),
            source=overrides.get("source", CallRecordingSource.WEBHOOK),
            call_data=overrides.get("call_data", {}),
            provider_call_id=overrides.get("provider_call_id"),
            provider_platform=overrides.get("provider_platform"),
            agent_id=overrides.get("agent_id"),
            evaluator_result_id=overrides.get("evaluator_result_id"),
        )
        db_session.add(call_recording)
        db_session.commit()
        db_session.refresh(call_recording)
        return call_recording

    return _make_call_recording


@pytest.fixture
def make_prompt_optimization_run(db_session, org_id, seed_org):
    def _make_prompt_optimization_run(**overrides):
        run = PromptOptimizationRun(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            agent_id=overrides["agent_id"],
            evaluator_id=overrides.get("evaluator_id"),
            voice_bundle_id=overrides.get("voice_bundle_id"),
            seed_prompt=overrides.get("seed_prompt", "seed prompt"),
            status=overrides.get("status", "pending"),
            config=overrides.get("config"),
            celery_task_id=overrides.get("celery_task_id"),
        )
        db_session.add(run)
        db_session.commit()
        db_session.refresh(run)
        return run

    return _make_prompt_optimization_run


@pytest.fixture
def make_prompt_optimization_candidate(db_session):
    def _make_prompt_optimization_candidate(**overrides):
        candidate = PromptOptimizationCandidate(
            id=overrides.get("id", uuid4()),
            optimization_run_id=overrides["optimization_run_id"],
            prompt_text=overrides.get("prompt_text", "candidate prompt"),
            score=overrides.get("score", 0.9),
            metric_breakdown=overrides.get("metric_breakdown"),
            reflection_summary=overrides.get("reflection_summary"),
            parent_candidate_id=overrides.get("parent_candidate_id"),
            is_accepted=overrides.get("is_accepted", False),
        )
        db_session.add(candidate)
        db_session.commit()
        db_session.refresh(candidate)
        return candidate

    return _make_prompt_optimization_candidate
