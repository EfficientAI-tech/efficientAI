"""API tests for observability routes."""


def test_list_get_delete_observability_calls(authenticated_client, make_call_recording):
    call_recording = make_call_recording(
        call_short_id="654321",
        source="webhook",
        call_data={"messages": [{"role": "user", "content": "hello"}]},
    )

    list_response = authenticated_client.get("/api/v1/observability/calls")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/observability/calls/{call_recording.call_short_id}")
    assert get_response.status_code == 200
    assert get_response.json()["call_short_id"] == "654321"

    delete_response = authenticated_client.delete(
        f"/api/v1/observability/calls/{call_recording.call_short_id}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Call deleted"


def test_playground_call_recordings_are_excluded_from_observability_list(
    authenticated_client, make_call_recording
):
    make_call_recording(
        call_short_id="111111",
        source="playground",
        provider_platform="retell",
        provider_call_id="playground-call-1",
        call_data={"messages": [{"role": "user", "content": "playground"}]},
    )
    make_call_recording(
        call_short_id="222222",
        source="webhook",
        provider_platform="retell",
        provider_call_id="live-call-1",
        call_data={"messages": [{"role": "user", "content": "live"}]},
    )

    list_response = authenticated_client.get("/api/v1/observability/calls")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["call_short_id"] == "222222"


def test_observability_webhook_does_not_reclassify_playground_call(
    client, api_key, authenticated_client, make_call_recording, db_session
):
    playground_call = make_call_recording(
        call_short_id="333333",
        source="playground",
        provider_platform="retell",
        provider_call_id="shared-provider-call-id",
        call_data={"messages": [{"role": "user", "content": "playground"}]},
    )

    webhook_response = client.post(
        f"/api/v1/observability/calls/webhook/{api_key}",
        json={
            "id": "shared-provider-call-id",
            "provider_platform": "retell",
            "messages": [{"role": "user", "content": "webhook update"}],
            "startedAt": "2025-10-15T09:22:21.787Z",
        },
    )
    assert webhook_response.status_code == 201
    assert webhook_response.json()["action"] == "skipped_playground"

    db_session.refresh(playground_call)
    assert playground_call.source.value == "playground"

    list_response = authenticated_client.get("/api/v1/observability/calls")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_evaluator_linked_calls_included_in_unified_observability_list(
    authenticated_client, make_evaluator_result, make_call_recording
):
    """Unified /calls hub lists webhook calls even when linked to evaluator results."""
    result = make_evaluator_result(result_id="556677")
    linked = make_call_recording(
        call_short_id="998877",
        evaluator_result_id=result.id,
        source="webhook",
        provider_platform="vobiz",
    )
    unlinked = make_call_recording(
        call_short_id="112233",
        source="webhook",
        call_data={"messages": [{"role": "user", "content": "live"}]},
    )

    list_response = authenticated_client.get("/api/v1/observability/calls")
    assert list_response.status_code == 200
    payload = list_response.json()
    call_short_ids = {row["call_short_id"] for row in payload}
    assert linked.call_short_id in call_short_ids
    assert unlinked.call_short_id in call_short_ids

    get_linked = authenticated_client.get("/api/v1/observability/calls/998877")
    assert get_linked.status_code == 200
    assert get_linked.json()["call_short_id"] == linked.call_short_id
