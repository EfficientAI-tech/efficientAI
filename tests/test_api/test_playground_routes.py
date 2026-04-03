"""API tests for playground routes."""


def test_list_playground_call_recordings(authenticated_client, make_call_recording):
    make_call_recording(call_short_id="111111", source="playground", call_data={"foo": "bar"})

    response = authenticated_client.get("/api/v1/playground/call-recordings")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["call_short_id"] == "111111"
