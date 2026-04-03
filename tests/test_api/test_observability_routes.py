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
