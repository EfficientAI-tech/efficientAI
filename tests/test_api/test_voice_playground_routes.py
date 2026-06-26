"""API tests for voice-playground routes."""

from uuid import uuid4

from app.dependencies import get_workspace_id
from app.models.database import (
    CallImport,
    CallImportRow,
    TTSComparison,
    TTSComparisonStatus,
    TTSSample,
    TTSSampleStatus,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


def test_list_tts_providers(authenticated_client, monkeypatch, make_ai_provider):
    from app.api.v1.routes import voice_playground as vp_routes

    make_ai_provider(provider="openai")
    monkeypatch.setattr(
        vp_routes,
        "_get_tts_models_by_provider",
        lambda: {"openai": ["gpt-4o-mini-tts"]},
    )
    monkeypatch.setattr(
        vp_routes.model_config_service,
        "get_voices_for_model",
        lambda _model_name: [{"id": "alloy", "name": "Alloy", "gender": "Neutral", "accent": "American"}],
    )

    response = authenticated_client.get("/api/v1/voice-playground/tts-providers")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["provider"] == "openai"


def test_tts_comparison_crud_and_actions(authenticated_client):
    create_payload = {
        "name": "OpenAI voice check",
        "provider_a": "openai",
        "model_a": "gpt-4o-mini-tts",
        "voices_a": [{"id": "alloy", "name": "Alloy"}],
        "sample_texts": ["Hello this is a test sample."],
        "num_runs": 1,
    }
    create_response = authenticated_client.post("/api/v1/voice-playground/comparisons", json=create_payload)
    assert create_response.status_code == 200
    comparison = create_response.json()
    comparison_id = comparison["id"]
    sample_id = comparison["samples"][0]["id"]

    list_response = authenticated_client.get("/api/v1/voice-playground/comparisons")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/voice-playground/comparisons/{comparison_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == comparison_id

    generate_response = authenticated_client.post(
        f"/api/v1/voice-playground/comparisons/{comparison_id}/generate"
    )
    assert generate_response.status_code == 200
    assert "task_id" in generate_response.json()

    blind_test_response = authenticated_client.post(
        f"/api/v1/voice-playground/comparisons/{comparison_id}/blind-test",
        json={"results": [{"sample_index": 0, "preferred": "A"}]},
    )
    assert blind_test_response.status_code == 200
    assert blind_test_response.json()["message"] == "Blind test results saved"

    sample_response = authenticated_client.get(
        f"/api/v1/voice-playground/comparisons/{comparison_id}/samples/{sample_id}"
    )
    assert sample_response.status_code == 200
    assert sample_response.json()["id"] == sample_id

    analytics_response = authenticated_client.get("/api/v1/voice-playground/analytics")
    assert analytics_response.status_code == 200
    assert isinstance(analytics_response.json(), list)

    delete_response = authenticated_client.delete(f"/api/v1/voice-playground/comparisons/{comparison_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Comparison deleted"


def test_voice_playground_call_import_rows_scope_to_workspace(
    authenticated_client, db_session, org_id, default_workspace
):
    workspace_b = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Workspace B",
        slug="workspace_b",
        is_default=False,
    )
    db_session.add(workspace_b)
    db_session.commit()

    default_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=default_workspace.id,
        provider="exotel",
        original_filename="default.csv",
        column_mapping={"external_call_id": "CallID"},
        extra_columns=[],
        custom_column_mapping={},
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    other_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_b.id,
        provider="exotel",
        original_filename="other.csv",
        column_mapping={"external_call_id": "CallID"},
        extra_columns=[],
        custom_column_mapping={},
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add_all([default_import, other_import])
    db_session.flush()

    db_session.add(
        CallImportRow(
            id=uuid4(),
            organization_id=org_id,
            call_import_id=default_import.id,
            row_index=0,
            conversation_id="conv-default",
            recording_s3_key="organizations/test/default.wav",
            status=CallImportRowStatus.COMPLETED,
        )
    )
    db_session.add(
        CallImportRow(
            id=uuid4(),
            organization_id=org_id,
            call_import_id=other_import.id,
            row_index=0,
            conversation_id="conv-other",
            recording_s3_key="organizations/test/other.wav",
            status=CallImportRowStatus.COMPLETED,
        )
    )
    db_session.commit()

    default_rows = authenticated_client.get(
        "/api/v1/voice-playground/call-import-rows"
    ).json()["items"]
    assert {row["conversation_id"] for row in default_rows} == {"conv-default"}

    app = authenticated_client.app
    previous = app.dependency_overrides[get_workspace_id]
    app.dependency_overrides[get_workspace_id] = lambda: workspace_b.id
    try:
        other_rows = authenticated_client.get(
            "/api/v1/voice-playground/call-import-rows"
        ).json()["items"]
    finally:
        app.dependency_overrides[get_workspace_id] = previous

    assert {row["conversation_id"] for row in other_rows} == {"conv-other"}


def test_voice_playground_comparisons_scope_to_workspace(
    authenticated_client, db_session, org_id, default_workspace
):
    workspace_b = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Workspace B",
        slug="workspace_b",
        is_default=False,
    )
    db_session.add(workspace_b)
    db_session.commit()

    default_comparison = TTSComparison(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=default_workspace.id,
        simulation_id="sim001",
        name="Default workspace sim",
        status=TTSComparisonStatus.COMPLETED.value,
        mode="benchmark",
        provider_a="openai",
        model_a="gpt-4o-mini-tts",
        voices_a=[{"id": "alloy", "name": "Alloy"}],
        sample_texts=["hello"],
        num_runs=1,
    )
    other_comparison = TTSComparison(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_b.id,
        simulation_id="sim002",
        name="Other workspace sim",
        status=TTSComparisonStatus.COMPLETED.value,
        mode="benchmark",
        provider_a="openai",
        model_a="gpt-4o-mini-tts",
        voices_a=[{"id": "alloy", "name": "Alloy"}],
        sample_texts=["hello"],
        num_runs=1,
    )
    db_session.add_all([default_comparison, other_comparison])
    db_session.commit()

    listing = authenticated_client.get("/api/v1/voice-playground/comparisons").json()
    assert len(listing) == 1
    assert listing[0]["name"] == "Default workspace sim"

    app = authenticated_client.app
    previous = app.dependency_overrides[get_workspace_id]
    app.dependency_overrides[get_workspace_id] = lambda: workspace_b.id
    try:
        listing = authenticated_client.get("/api/v1/voice-playground/comparisons").json()
    finally:
        app.dependency_overrides[get_workspace_id] = previous

    assert len(listing) == 1
    assert listing[0]["name"] == "Other workspace sim"


def test_blind_test_only_rejects_cross_workspace_tts_sample(
    authenticated_client, db_session, org_id, default_workspace
):
    workspace_b = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Workspace B",
        slug="workspace_b",
        is_default=False,
    )
    db_session.add(workspace_b)
    db_session.commit()

    other_comparison = TTSComparison(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_b.id,
        simulation_id="sim-b",
        name="Other workspace sim",
        status=TTSComparisonStatus.COMPLETED.value,
        mode="benchmark",
        provider_a="openai",
        model_a="gpt-4o-mini-tts",
        voices_a=[{"id": "alloy", "name": "Alloy"}],
        sample_texts=["hello"],
        num_runs=1,
    )
    db_session.add(other_comparison)
    db_session.flush()

    other_sample = TTSSample(
        id=uuid4(),
        comparison_id=other_comparison.id,
        organization_id=org_id,
        workspace_id=workspace_b.id,
        provider="openai",
        model="gpt-4o-mini-tts",
        voice_id="alloy",
        voice_name="Alloy",
        side="A",
        sample_index=0,
        run_index=0,
        text="hello",
        audio_s3_key="organizations/test/sample.wav",
        status=TTSSampleStatus.COMPLETED.value,
        source_type="tts",
    )
    db_session.add(other_sample)
    db_session.commit()

    response = authenticated_client.post(
        "/api/v1/voice-playground/comparisons",
        json={
            "mode": "blind_test_only",
            "name": "Cross workspace blind test",
            "pairs": [
                {
                    "text": "Pair 1",
                    "x": {"type": "tts_sample", "tts_sample_id": str(other_sample.id)},
                    "y": {"type": "tts_sample", "tts_sample_id": str(other_sample.id)},
                }
            ],
        },
    )

    assert response.status_code == 404


def _seed_blind_test_ready_comparison(db_session, org_id, workspace_id):
    comparison = TTSComparison(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        simulation_id="sim-blind-share",
        name="Blind share metering test",
        status=TTSComparisonStatus.COMPLETED.value,
        mode="benchmark",
        provider_a="openai",
        provider_b="elevenlabs",
        model_a="gpt-4o-mini-tts",
        model_b="eleven_multilingual_v2",
        voices_a=[{"id": "alloy", "name": "Alloy"}],
        voices_b=[{"id": "rachel", "name": "Rachel"}],
        sample_texts=["hello"],
        num_runs=1,
    )
    db_session.add(comparison)
    db_session.flush()

    db_session.add_all(
        [
            TTSSample(
                id=uuid4(),
                comparison_id=comparison.id,
                organization_id=org_id,
                workspace_id=workspace_id,
                provider="openai",
                model="gpt-4o-mini-tts",
                voice_id="alloy",
                voice_name="Alloy",
                side="A",
                sample_index=0,
                run_index=0,
                text="hello",
                audio_s3_key="organizations/test/a.wav",
                status=TTSSampleStatus.COMPLETED.value,
                source_type="tts",
            ),
            TTSSample(
                id=uuid4(),
                comparison_id=comparison.id,
                organization_id=org_id,
                workspace_id=workspace_id,
                provider="elevenlabs",
                model="eleven_multilingual_v2",
                voice_id="rachel",
                voice_name="Rachel",
                side="B",
                sample_index=0,
                run_index=0,
                text="hello",
                audio_s3_key="organizations/test/b.wav",
                status=TTSSampleStatus.COMPLETED.value,
                source_type="tts",
            ),
        ]
    )
    db_session.commit()
    return comparison


def test_create_blind_test_share_meters_only_on_first_create(
    authenticated_client, db_session, org_id, default_workspace, monkeypatch
):
    from app.api.v1.routes import voice_playground as vp_routes

    comparison = _seed_blind_test_ready_comparison(db_session, org_id, default_workspace.id)
    calls = []

    def _record_metering(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(vp_routes, "record_blind_test_share_created", _record_metering)

    payload = {"title": "Public blind test", "custom_metrics": []}
    first = authenticated_client.post(
        f"/api/v1/voice-playground/comparisons/{comparison.id}/share",
        json=payload,
    )
    assert first.status_code == 200

    second = authenticated_client.post(
        f"/api/v1/voice-playground/comparisons/{comparison.id}/share",
        json={"title": "Updated title", "custom_metrics": []},
    )
    assert second.status_code == 200

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == org_id
    assert kwargs["comparison_id"] == comparison.id
    assert kwargs["workspace_id"] == default_workspace.id

