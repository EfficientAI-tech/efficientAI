"""Tests for OTLP JSON parsing."""

import json

from app.services.synthetic_traces.otlp_ingest import parse_otlp_json


def test_parse_otlp_json_span_attributes():
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "abc123",
                                    "spanId": "def456",
                                    "name": "conversation",
                                    "attributes": [
                                        {
                                            "key": "conversation.id",
                                            "value": {"stringValue": "conv-1"},
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    ).encode()
    spans = parse_otlp_json(body)
    assert len(spans) == 1
    assert spans[0]["name"] == "conversation"
    assert spans[0]["attributes"]["conversation.id"] == "conv-1"
