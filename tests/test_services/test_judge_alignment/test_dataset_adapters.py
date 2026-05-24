"""Unit tests for app.services.judge_alignment.dataset_adapters.

Covers the pure helpers (no DB):

- _classify_speaker: maps webhook / diarization / word-style speaker
  labels to "agent" / "user" / None, with optional source_config
  overrides.
- split_segments_by_role: groups speaker_segments into rendered
  user / agent blobs; returns None when nothing is classifiable.
- _from_csv: parses AlignEval-style CSV uploads (id, input, output
  [, label]) with the same label aliases the LLM judge uses.

The DB-backed adapters (_from_transcripts, _from_metric_outputs) are
covered indirectly by the API route tests in Tier 3.
"""

import io

import pytest
from fastapi import HTTPException

from app.services.judge_alignment.dataset_adapters import (
    TRANSCRIPT_INPUT_FIELD,
    TRANSCRIPT_OUTPUT_FIELD,
    _classify_speaker,
    _from_csv,
    split_segments_by_role,
)


# ---------------------------------------------------------------------------
# _classify_speaker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["Agent", "agent", "ASSISTANT", " bot ", "ai", "voice_agent"],
)
def test_classify_speaker_word_labels_map_to_agent(label):
    assert _classify_speaker(label) == "agent"


@pytest.mark.parametrize(
    "label",
    ["User", "user", "CUSTOMER", " test_agent ", "caller"],
)
def test_classify_speaker_word_labels_map_to_user(label):
    assert _classify_speaker(label) == "user"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Speaker 2", "agent"),     # webhook convention (Vapi/Retell/...)
        ("speaker_2", "agent"),
        ("speaker2", "agent"),
        ("2", "agent"),
        ("Speaker 0", "agent"),     # observability convention
        ("Speaker 1", "user"),
        ("speaker_1", "user"),
    ],
)
def test_classify_speaker_numbered_diarization_labels(label, expected):
    assert _classify_speaker(label) == expected


@pytest.mark.parametrize("label", ["Speaker 9", "Random", "Speaker X", "chairman"])
def test_classify_speaker_returns_none_for_unknown_labels(label):
    assert _classify_speaker(label) is None


@pytest.mark.parametrize("label", [None, "", "   "])
def test_classify_speaker_returns_none_for_blank_input(label):
    assert _classify_speaker(label) is None


def test_classify_speaker_overrides_take_precedence_over_defaults():
    """An org with `agent_speaker="Speaker 1"` must override the default."""
    assert (
        _classify_speaker(
            "Speaker 1",
            agent_speaker="Speaker 1",
            user_speaker="Speaker 2",
        )
        == "agent"
    )
    assert (
        _classify_speaker(
            "Speaker 2",
            agent_speaker="Speaker 1",
            user_speaker="Speaker 2",
        )
        == "user"
    )


def test_classify_speaker_overrides_use_case_insensitive_match():
    assert (
        _classify_speaker(
            "speaker a",
            agent_speaker="Speaker A",
        )
        == "agent"
    )


# ---------------------------------------------------------------------------
# split_segments_by_role
# ---------------------------------------------------------------------------


def test_split_segments_groups_alternating_turns_into_role_blobs():
    segments = [
        {"speaker": "User", "text": "Hi, can you help me?"},
        {"speaker": "Agent", "text": "Of course! What's the issue?"},
        {"speaker": "User", "text": "My order is late."},
        {"speaker": "Agent", "text": "Let me check that for you."},
    ]

    result = split_segments_by_role(segments)

    assert result is not None
    assert result["user_turns"] == 2
    assert result["agent_turns"] == 2
    assert result["user"] == "User: Hi, can you help me?\nUser: My order is late."
    assert result["agent"] == (
        "Agent: Of course! What's the issue?\n"
        "Agent: Let me check that for you."
    )


def test_split_segments_skips_blank_text_segments():
    segments = [
        {"speaker": "User", "text": ""},
        {"speaker": "User", "text": "   "},
        {"speaker": "Agent", "text": "Hello"},
    ]

    result = split_segments_by_role(segments)

    assert result == {
        "user": "",
        "agent": "Agent: Hello",
        "user_turns": 0,
        "agent_turns": 1,
    }


def test_split_segments_drops_unclassifiable_speakers_silently():
    """Unmappable turns must NOT pollute either bucket."""
    segments = [
        {"speaker": "Speaker 9", "text": "noise"},
        {"speaker": "Agent", "text": "Hello"},
        {"speaker": "Unknown", "text": "more noise"},
    ]

    result = split_segments_by_role(segments)

    assert result is not None
    assert result["agent_turns"] == 1
    assert result["user_turns"] == 0
    assert "noise" not in result["user"]
    assert "noise" not in result["agent"]


def test_split_segments_returns_none_for_empty_or_missing_input():
    assert split_segments_by_role(None) is None
    assert split_segments_by_role([]) is None


def test_split_segments_returns_none_when_all_segments_unclassifiable():
    segments = [
        {"speaker": "Speaker 9", "text": "x"},
        {"speaker": "Random", "text": "y"},
    ]

    assert split_segments_by_role(segments) is None


def test_split_segments_uses_overrides_for_org_specific_diarization():
    segments = [
        {"speaker": "Spkr-A", "text": "agent says hi"},
        {"speaker": "Spkr-B", "text": "user replies"},
    ]

    result = split_segments_by_role(
        segments,
        agent_speaker="Spkr-A",
        user_speaker="Spkr-B",
    )

    assert result is not None
    assert result["agent"] == "Agent: agent says hi"
    assert result["user"] == "User: user replies"


def test_split_segments_ignores_non_dict_entries_safely():
    """Real `speaker_segments` payloads can include malformed entries."""
    segments = [
        "not a dict",  # type: ignore[list-item]
        {"speaker": "Agent", "text": "Hello"},
    ]

    result = split_segments_by_role(segments)  # type: ignore[arg-type]

    assert result is not None
    assert result["agent_turns"] == 1


def test_transcript_field_constants_match_route_layer():
    """The route layer hard-codes the same defaults; keep them in sync."""
    assert TRANSCRIPT_INPUT_FIELD == "user"
    assert TRANSCRIPT_OUTPUT_FIELD == "agent"


# ---------------------------------------------------------------------------
# _from_csv
# ---------------------------------------------------------------------------


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_from_csv_parses_required_columns_and_builds_external_id():
    csv_bytes = _csv(
        "id,input,output\n"
        "1,Hello,Hi there\n"
        "2,Bye,See you\n"
    )

    rows = list(_from_csv(csv_bytes, max_rows=10))

    assert len(rows) == 2
    assert rows[0]["external_id"] == "csv:1"
    assert rows[0]["input_text"] == "Hello"
    assert rows[0]["output_text"] == "Hi there"
    assert rows[0]["extra"] == {"source": "csv", "csv_id": "1"}
    # No label column => label not present in the row dict.
    assert "label" not in rows[0]


def test_from_csv_normalises_pass_fail_label_aliases():
    csv_bytes = _csv(
        "id,input,output,label\n"
        "1,a,b,1\n"
        "2,a,b,fail\n"
        "3,a,b,true\n"
        "4,a,b,0\n"
        "5,a,b,pass\n"
        "6,a,b,false\n"
        "7,a,b,\n"          # blank label -> no label key
        "8,a,b,unknown\n"   # unknown -> no label key
    )

    rows = list(_from_csv(csv_bytes, max_rows=20))

    assert [r.get("label") for r in rows] == [
        "fail", "fail", "fail", "pass", "pass", "pass", None, None,
    ]
    # Labeled rows also get a `labeled_by` marker for provenance.
    for r in rows[:6]:
        assert r["labeled_by"] == "csv-import"


def test_from_csv_skips_rows_with_blank_required_fields():
    csv_bytes = _csv(
        "id,input,output\n"
        ",input,output\n"   # missing id
        "1,,output\n"       # missing input
        "2,input,\n"        # missing output
        "3,ok,ok\n"
    )

    rows = list(_from_csv(csv_bytes, max_rows=10))

    assert len(rows) == 1
    assert rows[0]["external_id"] == "csv:3"


def test_from_csv_is_case_insensitive_for_header_columns():
    csv_bytes = _csv(
        "ID,Input,OUTPUT,Label\n"
        "1,hi,bye,fail\n"
    )

    rows = list(_from_csv(csv_bytes, max_rows=10))

    assert len(rows) == 1
    assert rows[0]["label"] == "fail"


def test_from_csv_strips_utf8_bom_from_excel_exports():
    """Excel writes CSVs with a UTF-8 BOM; the parser must tolerate it."""
    csv_bytes = "\ufeffid,input,output\n1,a,b\n".encode("utf-8")

    rows = list(_from_csv(csv_bytes, max_rows=10))

    assert len(rows) == 1
    assert rows[0]["external_id"] == "csv:1"


def test_from_csv_raises_400_on_missing_required_columns():
    csv_bytes = _csv("id,input\n1,hello\n")  # no `output`

    with pytest.raises(HTTPException) as exc:
        list(_from_csv(csv_bytes, max_rows=10))

    assert exc.value.status_code == 400
    assert "output" in str(exc.value.detail)


def test_from_csv_raises_400_when_max_rows_exceeded():
    csv_bytes = _csv(
        "id,input,output\n"
        "1,a,b\n"
        "2,a,b\n"
        "3,a,b\n"
    )

    with pytest.raises(HTTPException) as exc:
        list(_from_csv(csv_bytes, max_rows=2))

    assert exc.value.status_code == 400
    assert "max rows" in str(exc.value.detail).lower()


def test_from_csv_raises_400_when_file_is_not_utf8():
    # A byte that isn't valid UTF-8.
    bad_bytes = b"id,input,output\n1,h\xff,b\n"

    with pytest.raises(HTTPException) as exc:
        list(_from_csv(bad_bytes, max_rows=10))

    assert exc.value.status_code == 400
    assert "utf-8" in str(exc.value.detail).lower()


def test_from_csv_raises_400_when_no_header_row():
    # An empty file has no header at all.
    with pytest.raises(HTTPException) as exc:
        list(_from_csv(b"", max_rows=10))

    assert exc.value.status_code == 400


# Suppress unused-import warning for the one test that uses io implicitly.
_ = io
