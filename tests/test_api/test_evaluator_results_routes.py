"""API tests for evaluator results routes."""


def _blob_storage_service():
    """Resolve the blob storage singleton exposed as s3_service."""
    import importlib

    s3_module = importlib.import_module("app.services.storage.s3_service")
    return s3_module.s3_service


def test_derive_speaker_segments_supports_smallest_payload():
    from app.api.v1.routes.evaluator_results import _derive_speaker_segments_from_call_data

    segments = _derive_speaker_segments_from_call_data(
        {
            "transcript_object": [
                {"speaker": "User", "text": "hello", "start": 0.0, "end": 0.5},
                {"speaker": "Agent", "text": "hi there", "start": 0.6, "end": 1.2},
            ]
        },
        "smallest",
    )

    assert segments is not None
    assert len(segments) == 2
    assert segments[0]["speaker"] == "Speaker 1"
    assert segments[1]["speaker"] == "Speaker 2"


def test_list_and_get_evaluator_results(authenticated_client, make_evaluator_result):
    result = make_evaluator_result(result_id="778899", status="completed")

    list_response = authenticated_client.get("/api/v1/evaluator-results")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 0  # default excludes playground (evaluator_id is null)

    playground_response = authenticated_client.get("/api/v1/evaluator-results?playground=true")
    assert playground_response.status_code == 200
    assert len(playground_response.json()["items"]) == 1

    get_response = authenticated_client.get(f"/api/v1/evaluator-results/{result.result_id}")
    assert get_response.status_code == 200
    assert get_response.json()["result_id"] == "778899"


def test_list_evaluator_results_filter_by_agent_id(
    authenticated_client, make_agent, make_evaluator, make_evaluator_result
):
    agent_a = make_agent(name="Filter Agent A", agent_id="811111")
    agent_b = make_agent(name="Filter Agent B", agent_id="822222")
    evaluator_a = make_evaluator(agent_id=agent_a.id, evaluator_id="811111")
    evaluator_b = make_evaluator(agent_id=agent_b.id, evaluator_id="822222")
    make_evaluator_result(
        result_id="811122",
        evaluator_id=evaluator_a.id,
        agent_id=agent_a.id,
    )
    make_evaluator_result(
        result_id="822233",
        evaluator_id=evaluator_b.id,
        agent_id=agent_b.id,
    )

    all_response = authenticated_client.get("/api/v1/evaluator-results")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 2

    filtered = authenticated_client.get(f"/api/v1/evaluator-results?agent_id={agent_a.id}")
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["agent_id"] == str(agent_a.id)


def test_get_evaluator_result_metrics(authenticated_client, make_evaluator_result, make_metric):
    metric = make_metric(name="Professionalism")
    result = make_evaluator_result(
        result_id="445566",
        metric_scores={str(metric.id): {"value": 85, "type": "rating"}},
    )

    response = authenticated_client.get(f"/api/v1/evaluator-results/{result.result_id}/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["result_id"] == "445566"
    assert "Professionalism" in body["metrics"]
    assert body["metrics"]["Professionalism"]["value"] == 85


def test_delete_evaluator_result(authenticated_client, make_evaluator_result):
    result = make_evaluator_result(result_id="334455")

    response = authenticated_client.delete(f"/api/v1/evaluator-results/{result.result_id}")

    assert response.status_code == 204


def test_delete_evaluator_result_with_linked_call_recording(
    authenticated_client,
    db_session,
    make_evaluator_result,
    make_call_recording,
):
    result = make_evaluator_result(result_id="221133")
    recording = make_call_recording(
        call_short_id="887766",
        evaluator_result_id=result.id,
        provider_platform="vobiz",
    )

    response = authenticated_client.delete(f"/api/v1/evaluator-results/{result.result_id}")

    assert response.status_code == 204
    db_session.refresh(recording)
    assert recording.evaluator_result_id is None


def test_delete_evaluator_results_bulk_with_linked_call_recording(
    authenticated_client,
    db_session,
    make_evaluator_result,
    make_call_recording,
):
    r1 = make_evaluator_result(result_id="111222")
    r2 = make_evaluator_result(result_id="333444")
    rec1 = make_call_recording(call_short_id="111111", evaluator_result_id=r1.id)
    rec2 = make_call_recording(call_short_id="222222", evaluator_result_id=r2.id)

    response = authenticated_client.delete(
        "/api/v1/evaluator-results",
        params={"result_ids": [str(r1.id), str(r2.id)]},
    )

    assert response.status_code == 204
    db_session.refresh(rec1)
    db_session.refresh(rec2)
    assert rec1.evaluator_result_id is None
    assert rec2.evaluator_result_id is None


def test_list_evaluator_results_scenario_and_status_filters(
    authenticated_client, make_agent, make_evaluator, make_evaluator_result, make_scenario
):
    agent = make_agent(name="Scenario Filter Agent")
    scenario_a = make_scenario(agent_id=agent.id, name="Scenario A")
    scenario_b = make_scenario(agent_id=agent.id, name="Scenario B")
    evaluator_a = make_evaluator(
        agent_id=agent.id, scenario_id=scenario_a.id, evaluator_id="911111"
    )
    evaluator_b = make_evaluator(
        agent_id=agent.id, scenario_id=scenario_b.id, evaluator_id="922222"
    )
    make_evaluator_result(
        result_id="111001",
        evaluator_id=evaluator_a.id,
        agent_id=agent.id,
        scenario_id=scenario_a.id,
        status="completed",
    )
    make_evaluator_result(
        result_id="111002",
        evaluator_id=evaluator_b.id,
        agent_id=agent.id,
        scenario_id=scenario_b.id,
        status="failed",
    )

    scen_resp = authenticated_client.get(
        f"/api/v1/evaluator-results?scenario_id={scenario_a.id}"
    )
    assert scen_resp.status_code == 200
    assert scen_resp.json()["total"] == 1
    assert scen_resp.json()["items"][0]["scenario"]["name"] == "Scenario A"

    failed_resp = authenticated_client.get("/api/v1/evaluator-results?status=failed")
    assert failed_resp.status_code == 200
    assert failed_resp.json()["total"] == 1
    assert failed_resp.json()["items"][0]["result_id"] == "111002"


def test_evaluator_results_overview_and_aggregate(
    authenticated_client,
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
):
    from app.models.database import EvaluatorSuite

    agent = make_agent(name="Overview Agent")
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id, name="Overview Scenario")
    suite = EvaluatorSuite(
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        name="Overview Suite",
        agent_id=agent.id,
        persona_id=persona.id,
    )
    db_session.add(suite)
    db_session.commit()
    db_session.refresh(suite)

    evaluator = make_evaluator(
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        suite_id=suite.id,
    )
    make_evaluator_result(
        result_id="555001",
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status="completed",
        metric_scores={"m1": {"value": True, "type": "boolean", "metric_name": "Pass"}},
    )

    overview = authenticated_client.get("/api/v1/evaluator-results/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["workspace_counts"]["total"] >= 1
    assert any(a["agent_id"] == str(agent.id) for a in body["agents"])

    suite_overview = authenticated_client.get(
        f"/api/v1/evaluator-results/overview?suite_id={suite.id}"
    )
    assert suite_overview.status_code == 200
    suite_body = suite_overview.json()
    assert suite_body["agents"][0]["suites"][0]["scenarios"][0]["scenario_name"] == "Overview Scenario"

    aggregate = authenticated_client.get(
        f"/api/v1/evaluator-results/aggregate?suite_id={suite.id}"
    )
    assert aggregate.status_code == 200
    agg = aggregate.json()
    assert agg["total_rows"] == 1
    assert agg["completed_rows"] == 1


def test_stream_evaluator_result_audio_from_s3(
    authenticated_client, make_evaluator_result, monkeypatch
):
    storage = _blob_storage_service()

    make_evaluator_result(
        result_id="991122",
        audio_s3_key="audio/organizations/test/evaluations/call-1/recording.mp3",
        provider_platform="elevenlabs",
        call_data={
            "recording_url": "https://api.elevenlabs.io/v1/convai/conversations/x/audio",
        },
    )

    monkeypatch.setattr(storage, "is_enabled", lambda: True)
    monkeypatch.setattr(
        storage,
        "download_file_by_key",
        lambda _key: b"fake-audio-bytes",
    )

    response = authenticated_client.get("/api/v1/evaluator-results/991122/audio")

    assert response.status_code == 200
    assert response.content == b"fake-audio-bytes"
    assert response.headers["content-type"] == "audio/mpeg"


def test_stream_evaluator_result_audio_proxies_elevenlabs(
    authenticated_client,
    make_agent,
    make_integration,
    make_evaluator_result,
    monkeypatch,
):
    from app.models.enums import IntegrationPlatform

    integration = make_integration(
        platform=IntegrationPlatform.ELEVENLABS.value,
        api_key="enc-key",
    )
    agent = make_agent(integration=integration)
    make_evaluator_result(
        result_id="992233",
        agent_id=agent.id,
        audio_s3_key=None,
        provider_platform="elevenlabs",
        provider_call_id="conv-123",
        call_data={
            "recording_urls": {
                "conversation_audio": (
                    "https://api.elevenlabs.io/v1/convai/conversations/conv-123/audio"
                ),
            },
        },
    )

    monkeypatch.setattr("app.core.encryption.decrypt_api_key", lambda _key: "test-xi-key")

    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "audio/mpeg"}

        def iter_content(self, chunk_size=8192):
            yield b"proxied-audio"

    def fake_get(url, headers=None, stream=False, timeout=60):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    response = authenticated_client.get("/api/v1/evaluator-results/992233/audio")

    assert response.status_code == 200
    assert response.content == b"proxied-audio"
    assert captured["headers"]["xi-api-key"] == "test-xi-key"


def test_stream_evaluator_result_audio_proxies_vapi_with_bearer(
    authenticated_client,
    make_agent,
    make_integration,
    make_evaluator_result,
    monkeypatch,
):
    from app.models.enums import IntegrationPlatform

    integration = make_integration(
        platform=IntegrationPlatform.VAPI.value,
        api_key="enc-vapi-key",
    )
    agent = make_agent(integration=integration)
    make_evaluator_result(
        result_id="994455",
        agent_id=agent.id,
        audio_s3_key=None,
        provider_platform="vapi",
        call_data={"recordingUrl": "https://storage.vapi.ai/recording.wav"},
    )

    monkeypatch.setattr("app.core.encryption.decrypt_api_key", lambda _key: "vapi-private-key")

    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "audio/wav"}

        def iter_content(self, chunk_size=8192):
            yield b"vapi-audio"

    def fake_get(url, headers=None, stream=False, timeout=60):
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    response = authenticated_client.get("/api/v1/evaluator-results/994455/audio")

    assert response.status_code == 200
    assert response.content == b"vapi-audio"
    assert captured["headers"]["Authorization"] == "Bearer vapi-private-key"


def test_stream_evaluator_result_audio_redirects_vapi_presigned_url(
    authenticated_client,
    make_evaluator_result,
):
    signed_url = (
        "https://hipaa-recordings.example/recording.wav?"
        "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
    )
    make_evaluator_result(
        result_id="994466",
        audio_s3_key=None,
        provider_platform="vapi",
        call_data={
            "artifact": {
                "presignedMonoUrl": signed_url,
                "recordingUrl": "https://raw.example/recording.wav",
            }
        },
    )

    response = authenticated_client.get(
        "/api/v1/evaluator-results/994466/audio",
        follow_redirects=False,
    )

    assert response.status_code in {302, 307}
    assert response.headers["location"] == signed_url


def test_stream_evaluator_result_audio_not_found(
    authenticated_client, make_evaluator_result
):
    make_evaluator_result(
        result_id="993344",
        audio_s3_key=None,
        provider_platform="elevenlabs",
        call_data={},
    )

    response = authenticated_client.get("/api/v1/evaluator-results/993344/audio")

    assert response.status_code == 404


def test_re_evaluate_downloads_vapi_audio_with_bearer(
    authenticated_client,
    make_agent,
    make_integration,
    make_evaluator,
    make_evaluator_result,
    monkeypatch,
):
    from app.models.enums import IntegrationPlatform

    integration = make_integration(
        platform=IntegrationPlatform.VAPI.value,
        api_key="enc",
    )
    agent = make_agent(integration=integration)
    evaluator = make_evaluator(agent_id=agent.id, evaluator_id="881122")
    result = make_evaluator_result(
        result_id="665544",
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        audio_s3_key=None,
        provider_platform="vapi",
        provider_call_id="call-vapi-1",
        transcription="hello world",
        call_data={"recordingUrl": "https://storage.vapi.ai/recording.wav"},
    )

    captured = {}

    class FakeResp:
        status_code = 200
        content = b"audio-bytes"
        headers = {"content-type": "audio/mpeg"}

    def fake_get(url, headers=None, timeout=120):
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("app.core.encryption.decrypt_api_key", lambda _key: "vapi-secret")
    storage = _blob_storage_service()
    monkeypatch.setattr(
        storage,
        "upload_file_by_key",
        lambda *_args, **_kwargs: None,
    )

    class FakeTask:
        id = "task-1"

    monkeypatch.setattr(
        "app.workers.celery_app.process_evaluator_result_task.delay",
        lambda *_args, **_kwargs: FakeTask(),
    )

    response = authenticated_client.post(
        f"/api/v1/evaluator-results/{result.result_id}/re-evaluate"
    )

    assert response.status_code == 200
    assert captured["headers"]["Authorization"] == "Bearer vapi-secret"


def test_re_evaluate_playground_result_without_evaluator_id(
    authenticated_client,
    make_agent,
    make_evaluator_result,
    monkeypatch,
):
    agent = make_agent()
    result = make_evaluator_result(
        result_id="776655",
        evaluator_id=None,
        agent_id=agent.id,
        transcription="Speaker 1: hello\nSpeaker 2: hi there",
        provider_platform="vapi",
        status="completed",
    )

    class FakeTask:
        id = "task-playground-re-eval"

    monkeypatch.setattr(
        "app.workers.celery_app.process_evaluator_result_task.delay",
        lambda *_args, **_kwargs: FakeTask(),
    )

    response = authenticated_client.post(
        f"/api/v1/evaluator-results/{result.result_id}/re-evaluate"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"

