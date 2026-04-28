"""API tests for playground routes."""


def test_extract_transcript_from_smallest_call_data():
    from app.api.v1.routes.playground import extract_transcript_from_call_data

    transcript_text, segments = extract_transcript_from_call_data(
        {
            "transcript_object": [
                {"speaker": "User", "text": "hello", "start": 0.0, "end": 0.4},
                {"speaker": "Agent", "text": "hi", "start": 0.6, "end": 1.0},
            ]
        },
        "smallest",
    )

    assert transcript_text == "User: hello\nAgent: hi"
    assert len(segments) == 2
    assert segments[0]["speaker"] == "User"


def test_list_playground_call_recordings(authenticated_client, make_call_recording):
    make_call_recording(call_short_id="111111", source="playground", call_data={"foo": "bar"})

    response = authenticated_client.get("/api/v1/playground/call-recordings")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["call_short_id"] == "111111"
