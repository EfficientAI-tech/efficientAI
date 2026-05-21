"""Tests for the transcription + configurable-LLM additions on call imports.

These cover the new pieces from migration 031 / the
``call_import_diarization_eval_viz`` plan:

* ``transcribe_call_import_row`` worker — confirms it asks the
  transcription service for *plain* text (no pyannote diarization) and
  stores the result on the row with the right provenance fields.
* The aggregation helper used by both the per-run Visualizations tab
  and the cross-run Insights tab.
* The Run Evaluation create payload validation for ``llm_provider``,
  ``metric_llm_overrides`` and ``auto_transcribe``.
* The transcribe API endpoints (skip / queue counts).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# transcribe_call_import_row worker — plain-transcript mode
# ---------------------------------------------------------------------------


def _make_fake_row():
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        recording_s3_key="s3://bucket/key.wav",
        transcript="production value from CSV",
        transcript_source="csv",
        transcript_status="idle",
        transcript_error=None,
        transcript_provider=None,
        transcript_model=None,
        transcribed_at=None,
        diarised_transcript=None,
        diarised_segments=None,
        diarised_speaker_swap=False,
        diarised_transcript_status="idle",
        diarised_transcript_error=None,
        diarised_transcript_provider=None,
        diarised_transcript_model=None,
        diarised_llm_provider=None,
        diarised_llm_model=None,
        diarised_llm_credential_id=None,
        diarised_prompt=None,
        diarised_at=None,
        celery_task_id=None,
    )


def _patch_session(monkeypatch, task_module, fake_row):
    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.first.return_value = fake_row

    fake_db = SimpleNamespace(
        query=lambda *_a, **_kw: fake_query,
        commit=lambda: None,
        close=lambda: None,
    )
    monkeypatch.setattr(task_module, "SessionLocal", lambda: fake_db)
    return fake_db


def _resolve_submodule(dotted: str):
    """Get the actual submodule object even when the parent package's
    ``__init__.py`` re-exports something with the same name.

    Specifically, ``app/services/ai/__init__.py`` runs
    ``from app.services.ai.transcription_service import transcription_service``
    which **overwrites** the submodule attribute on the parent package
    with the singleton instance. After that, ``getattr`` walks
    (``import X.Y.Z`` / ``import X.Y.Z as alias`` /
    ``monkeypatch.setattr("X.Y.Z…", …)``) all return the singleton, not
    the submodule, so patching anything on "the module" via name
    resolution silently targets the instance and crashes with an
    ``AttributeError`` on the next attribute lookup.

    ``importlib.import_module`` reads ``sys.modules`` directly which
    bypasses the parent-namespace ``getattr`` lookup and reliably
    returns the submodule object.
    """
    import importlib

    return importlib.import_module(dotted)


def _patch_transcription_service(monkeypatch, fake_service):
    """Stub the ``transcription_service`` singleton the worker reads
    via its lazy ``from app.services.ai.transcription_service import
    transcription_service`` call.

    See :func:`_resolve_submodule` for why we go through
    ``importlib.import_module`` instead of the usual ``import …`` form.
    """
    ts_mod = _resolve_submodule("app.services.ai.transcription_service")
    monkeypatch.setattr(ts_mod, "transcription_service", fake_service)


def _patch_llm_diariser(monkeypatch, fake):
    """Stub the LLM diariser entry-point the worker reads via its lazy
    ``from app.workers.tasks.helpers.llm_diarisation import
    diarize_transcript_with_llm`` import. Uses
    :func:`_resolve_submodule` for the same reason as
    :func:`_patch_transcription_service`."""
    diariser_mod = _resolve_submodule(
        "app.workers.tasks.helpers.llm_diarisation"
    )
    monkeypatch.setattr(diariser_mod, "diarize_transcript_with_llm", fake)


def test_transcribe_worker_skips_pyannote_and_calls_llm_diariser(monkeypatch):
    """Worker should request plain STT text (no pyannote) and hand the
    transcript to the LLM diariser helper. Output lands on
    ``diarised_transcript`` / ``diarised_segments`` with the diariser
    provenance recorded."""
    from app.workers.tasks import transcribe_call_import_row as task_module

    captured: dict = {}

    def _fake_transcribe(**kwargs):
        captured["stt_kwargs"] = kwargs
        return {"transcript": "hello there. hi back.", "speaker_segments": None}

    fake_service = SimpleNamespace(transcribe=_fake_transcribe)

    def _fake_diarise(transcript, **kwargs):
        captured["llm_kwargs"] = kwargs
        captured["llm_transcript"] = transcript
        return [
            {
                "speaker": "Speaker 1",
                "text": "hello there.",
                "start": 0.0,
                "end": 1.0,
            },
            {
                "speaker": "Speaker 2",
                "text": "hi back.",
                "start": 1.0,
                "end": 2.0,
            },
        ]

    fake_row = _make_fake_row()
    _patch_session(monkeypatch, task_module, fake_row)
    _patch_transcription_service(monkeypatch, fake_service)
    _patch_llm_diariser(monkeypatch, _fake_diarise)

    result = task_module.transcribe_call_import_row_task.run(
        str(fake_row.id),
        "deepgram",
        "nova-2",
        None,  # credential
        None,  # language
        False,  # overwrite
        None,  # run_eval_row_id
        "openai",
        "gpt-4o-mini",
        None,
        "  Diarise it!  ",
    )

    assert result["status"] == "completed"
    # Pyannote is NEVER asked to run from this worker any more — we
    # diarise via LLM in the second pass.
    assert captured["stt_kwargs"]["enable_speaker_diarization"] is False
    # The LLM diariser got the plain STT text + the custom prompt
    # the user supplied (trimmed, never the raw whitespace).
    assert captured["llm_transcript"] == "hello there. hi back."
    assert captured["llm_kwargs"]["custom_prompt"] == "Diarise it!"
    assert captured["llm_kwargs"]["llm_provider"] == "openai"
    assert captured["llm_kwargs"]["llm_model"] == "gpt-4o-mini"

    # Production transcript untouched.
    assert fake_row.transcript == "production value from CSV"
    # Diarised rendering uses agent/user labels (first speaker by
    # start time becomes the agent).
    assert fake_row.diarised_transcript == (
        "agent: hello there.\nuser: hi back."
    )
    assert fake_row.diarised_segments is not None
    assert len(fake_row.diarised_segments) == 2
    assert fake_row.diarised_segments[0]["speaker"] == "agent"
    assert fake_row.diarised_segments[1]["speaker"] == "user"
    assert fake_row.diarised_speaker_swap is False
    assert fake_row.diarised_transcript_provider == "deepgram"
    assert fake_row.diarised_transcript_model == "nova-2"
    # Diariser provenance is persisted alongside the STT provenance.
    assert fake_row.diarised_llm_provider == "openai"
    assert fake_row.diarised_llm_model == "gpt-4o-mini"
    assert fake_row.diarised_prompt == "Diarise it!"
    assert fake_row.diarised_transcript_status == "completed"
    assert fake_row.diarised_transcript_error is None


def test_transcribe_worker_fails_when_diariser_llm_missing(monkeypatch):
    """Missing diariser provider/model is a typed failure: the row is
    marked failed with an actionable message, no STT call is made."""
    from app.workers.tasks import transcribe_call_import_row as task_module

    stt_calls = []

    def _fake_transcribe(**kwargs):
        stt_calls.append(kwargs)
        return {"transcript": "x", "speaker_segments": None}

    fake_service = SimpleNamespace(transcribe=_fake_transcribe)
    fake_row = _make_fake_row()
    _patch_session(monkeypatch, task_module, fake_row)
    _patch_transcription_service(monkeypatch, fake_service)

    result = task_module.transcribe_call_import_row_task.run(
        str(fake_row.id), "deepgram", "nova-2"
    )

    assert result == {"status": "failed", "reason": "missing_llm_diariser"}
    assert stt_calls == []
    assert fake_row.diarised_transcript_status == "failed"
    assert "diarisation llm" in (
        fake_row.diarised_transcript_error or ""
    ).lower()


def test_transcribe_worker_surfaces_llm_diariser_errors(monkeypatch):
    """``LLMDiarisationError`` from the helper must land verbatim on
    ``diarised_transcript_error`` so the modal can show "your prompt
    didn't return JSON" without the operator having to read worker
    logs."""
    from app.workers.tasks import transcribe_call_import_row as task_module
    from app.workers.tasks.helpers.llm_diarisation import LLMDiarisationError

    fake_service = SimpleNamespace(
        transcribe=lambda **_kw: {
            "transcript": "single voice mumble",
            "speaker_segments": None,
        }
    )

    def _boom(_transcript, **_kwargs):
        raise LLMDiarisationError("Model returned prose instead of JSON.")

    fake_row = _make_fake_row()
    _patch_session(monkeypatch, task_module, fake_row)
    _patch_transcription_service(monkeypatch, fake_service)
    _patch_llm_diariser(monkeypatch, _boom)

    result = task_module.transcribe_call_import_row_task.run(
        str(fake_row.id),
        "deepgram",
        "nova-2",
        None,
        None,
        False,
        None,
        "openai",
        "gpt-4o-mini",
    )

    assert result == {"status": "failed", "reason": "llm_diarisation_error"}
    assert fake_row.diarised_transcript_status == "failed"
    assert "JSON" in (fake_row.diarised_transcript_error or "")


def test_transcribe_worker_marks_failed_on_empty_transcript(monkeypatch):
    """Empty STT output short-circuits before the LLM diariser runs —
    we don't burn LLM tokens on a transcript that's already empty."""
    from app.workers.tasks import transcribe_call_import_row as task_module

    fake_service = SimpleNamespace(
        transcribe=lambda **_kw: {"transcript": "   ", "speaker_segments": None}
    )

    diariser_calls = []

    def _track(*args, **kwargs):
        diariser_calls.append((args, kwargs))
        return []

    fake_row = _make_fake_row()
    fake_row.transcript = None
    _patch_session(monkeypatch, task_module, fake_row)
    _patch_transcription_service(monkeypatch, fake_service)
    _patch_llm_diariser(monkeypatch, _track)

    result = task_module.transcribe_call_import_row_task.run(
        str(fake_row.id),
        "deepgram",
        "nova-2",
        None,
        None,
        False,
        None,
        "openai",
        "gpt-4o-mini",
    )

    assert result == {"status": "failed", "reason": "empty_transcript"}
    assert fake_row.diarised_transcript_status == "failed"
    assert "empty" in (fake_row.diarised_transcript_error or "").lower()
    # The diariser must not be called when the transcript is empty.
    assert diariser_calls == []


# ---------------------------------------------------------------------------
# Aggregate helper used by the Visualizations + Insights tabs
# ---------------------------------------------------------------------------


def test_compute_metric_aggregates_handles_numeric_and_categorical():
    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
    )

    # Stub out _metrics_for_ids so the helper doesn't go to the DB.
    metric_id_num = uuid4()
    metric_id_cat = uuid4()
    fake_metric_num = SimpleNamespace(
        id=metric_id_num, name="Adherence", metric_type="rating"
    )
    fake_metric_cat = SimpleNamespace(
        id=metric_id_cat, name="Outcome", metric_type="pass_fail"
    )

    evaluation = SimpleNamespace(
        organization_id=uuid4(),
        selected_metric_ids=[str(metric_id_num), str(metric_id_cat)],
    )

    eval_rows = [
        SimpleNamespace(
            metric_scores={
                str(metric_id_num): {"value": 0.5, "type": "rating"},
                str(metric_id_cat): {"value": "pass", "type": "pass_fail"},
            }
        ),
        SimpleNamespace(
            metric_scores={
                str(metric_id_num): {"value": 0.75, "type": "rating"},
                str(metric_id_cat): {"value": "fail", "type": "pass_fail"},
            }
        ),
        SimpleNamespace(
            metric_scores={
                str(metric_id_num): {
                    "value": None,
                    "type": "rating",
                    "skipped": "audio_required",
                },
                str(metric_id_cat): {"value": "pass", "type": "pass_fail"},
            }
        ),
    ]

    with patch(
        "app.api.v1.routes.call_import_evaluations._metrics_for_ids",
        return_value=[fake_metric_num, fake_metric_cat],
    ):
        aggregates = _compute_metric_aggregates(
            db=MagicMock(), evaluation=evaluation, eval_rows=eval_rows
        )

    by_id = {a.metric_id: a for a in aggregates}
    num_agg = by_id[str(metric_id_num)]
    cat_agg = by_id[str(metric_id_cat)]

    # Numeric metric: only completed values count toward stats; skipped
    # entries are tracked separately.
    assert num_agg.count == 2
    assert num_agg.skipped_count == 1
    assert pytest.approx(num_agg.mean, rel=1e-6) == 0.625
    assert num_agg.min == 0.5
    assert num_agg.max == 0.75
    assert len(num_agg.histogram_buckets) >= 1

    # Categorical metric: value_counts beats histogram; ranked by frequency.
    assert cat_agg.count == 3
    labels = [vc.label for vc in cat_agg.value_counts]
    assert labels[0] == "pass"
    assert {vc.label for vc in cat_agg.value_counts} == {"pass", "fail"}


def test_compute_metric_aggregates_treats_booleans_as_categorical():
    """Booleans should not collapse into a degenerate {0,1} histogram."""
    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
    )

    metric_id = uuid4()
    fake_metric = SimpleNamespace(
        id=metric_id, name="Resolved", metric_type="binary"
    )

    evaluation = SimpleNamespace(
        organization_id=uuid4(),
        selected_metric_ids=[str(metric_id)],
    )
    eval_rows = [
        SimpleNamespace(metric_scores={str(metric_id): {"value": True}}),
        SimpleNamespace(metric_scores={str(metric_id): {"value": False}}),
        SimpleNamespace(metric_scores={str(metric_id): {"value": True}}),
    ]

    with patch(
        "app.api.v1.routes.call_import_evaluations._metrics_for_ids",
        return_value=[fake_metric],
    ):
        aggregates = _compute_metric_aggregates(
            db=MagicMock(), evaluation=evaluation, eval_rows=eval_rows
        )

    [agg] = aggregates
    # Histogram should be empty (all values are bool); category_counts wins.
    assert agg.histogram_buckets == []
    label_counts = {vc.label: vc.count for vc in agg.value_counts}
    assert label_counts == {"true": 2, "false": 1}


# ---------------------------------------------------------------------------
# Run Evaluation create payload — LLM + auto_transcribe validation
# ---------------------------------------------------------------------------


def test_create_evaluation_payload_validates_llm_provider_and_model_pair():
    from app.models.schemas import (
        CallImportEvaluationCreate,
        CallImportEvaluationLLMOverride,
    )

    # Both empty: ok (legacy default).
    payload = CallImportEvaluationCreate(metric_ids=[uuid4()])
    assert payload.llm_provider is None
    assert payload.llm_model is None

    # Override with both: ok.
    payload = CallImportEvaluationCreate(
        metric_ids=[uuid4()],
        llm_provider="anthropic",
        llm_model="claude-3-opus",
    )
    assert payload.llm_provider == "anthropic"
    assert payload.llm_model == "claude-3-opus"

    # Per-metric overrides round-trip cleanly.
    metric_id = uuid4()
    payload = CallImportEvaluationCreate(
        metric_ids=[metric_id],
        metric_llm_overrides={
            str(metric_id): CallImportEvaluationLLMOverride(
                provider="openai", model="gpt-4o"
            )
        },
    )
    assert payload.metric_llm_overrides is not None
    assert (
        payload.metric_llm_overrides[str(metric_id)].provider == "openai"
    )


def test_create_evaluation_payload_defaults_transcript_sources_to_diarised():
    """``transcript_sources`` defaults to ``['diarised']`` so legacy
    clients that omit the field get the new diarised-only behavior
    without having to opt in explicitly."""
    from app.models.schemas import CallImportEvaluationCreate

    payload = CallImportEvaluationCreate(metric_ids=[uuid4()])
    assert payload.transcript_sources == ["diarised"]


def test_create_evaluation_payload_rejects_production_transcript_source():
    """The legacy ``production`` transcript source is no longer accepted
    — the schema-level validator must reject it with a clear message so
    the route handler never even sees it."""
    import pytest as _pytest
    from pydantic import ValidationError

    from app.models.schemas import CallImportEvaluationCreate

    with _pytest.raises(ValidationError) as exc:
        CallImportEvaluationCreate(
            metric_ids=[uuid4()],
            transcript_sources=["production"],
        )
    msg = str(exc.value)
    assert "diarised" in msg.lower() or "production" in msg.lower()


def test_create_evaluation_payload_accepts_explicit_diarised_source():
    """Sending the explicit single-element ``['diarised']`` round-trips
    cleanly — this is the shape the frontend sends on every run."""
    from app.models.schemas import CallImportEvaluationCreate

    payload = CallImportEvaluationCreate(
        metric_ids=[uuid4()], transcript_sources=["diarised"]
    )
    assert payload.transcript_sources == ["diarised"]


# ---------------------------------------------------------------------------
# transcribe_call_import endpoint helper
# ---------------------------------------------------------------------------


def test_select_rows_for_transcription_skips_rows_with_existing_transcripts():
    """``only_missing=True`` (default) keeps rows that already have a
    diarised transcript; the production transcript is irrelevant — it
    lives in a separate column the worker never touches."""
    from app.api.v1.routes.call_imports import _select_rows_for_transcription
    from app.models.schemas import CallImportTranscribeRequest

    call_import = SimpleNamespace(id=uuid4())

    fake_rows = [
        # Already diarised → skip.
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-1",
            transcript=None,
            diarised_transcript="present",
            row_index=0,
        ),
        # No diarised transcript, has recording → selected.
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-2",
            transcript=None,
            diarised_transcript=None,
            row_index=1,
        ),
        # No recording → skipped regardless.
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key=None,
            transcript=None,
            diarised_transcript=None,
            row_index=2,
        ),
        # Production transcript present but no diarised yet → selected
        # (production transcript is ignored by the diarisation worker).
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-4",
            transcript="csv production",
            diarised_transcript=None,
            row_index=3,
        ),
    ]

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = SimpleNamespace(
        all=lambda: fake_rows
    )

    fake_db = SimpleNamespace(query=lambda *_: fake_query)

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
        only_missing=True,
        overwrite_existing=False,
    )
    selected, skip_counts = _select_rows_for_transcription(
        fake_db, call_import, payload
    )

    # Two rows selected: the bare row, and the one with only a production
    # transcript.
    assert len(selected) == 2
    selected_keys = {r.recording_s3_key for r in selected}
    assert selected_keys == {"s3-2", "s3-4"}
    assert skip_counts.get("transcript_present") == 1
    assert skip_counts.get("no_recording") == 1


def test_select_rows_for_transcription_overwrite_replaces_existing():
    from app.api.v1.routes.call_imports import _select_rows_for_transcription
    from app.models.schemas import CallImportTranscribeRequest

    call_import = SimpleNamespace(id=uuid4())

    fake_rows = [
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-1",
            transcript=None,
            diarised_transcript="present",
            row_index=0,
        ),
    ]
    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = SimpleNamespace(
        all=lambda: fake_rows
    )
    fake_db = SimpleNamespace(query=lambda *_: fake_query)

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
        only_missing=True,
        overwrite_existing=True,
    )
    selected, skip_counts = _select_rows_for_transcription(
        fake_db, call_import, payload
    )

    assert len(selected) == 1
    assert skip_counts == {}


def test_select_rows_for_transcription_raises_on_unknown_row_id():
    from app.api.v1.routes.call_imports import _select_rows_for_transcription
    from app.models.schemas import CallImportTranscribeRequest

    call_import = SimpleNamespace(id=uuid4())
    requested_id = uuid4()

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = SimpleNamespace(all=lambda: [])
    fake_db = SimpleNamespace(query=lambda *_: fake_query)

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
    )

    with pytest.raises(HTTPException) as exc:
        _select_rows_for_transcription(
            fake_db, call_import, payload, requested_row_ids=[requested_id]
        )
    assert exc.value.status_code == 400
    assert str(requested_id) in exc.value.detail


# ---------------------------------------------------------------------------
# Speaker-turn helpers — pure functions used by transcribe_call_import_row
# ---------------------------------------------------------------------------


def test_segments_to_user_agent_turns_assigns_first_speaker_to_agent():
    """The heuristic is "first speaker by start time is the agent"; the
    next distinct label becomes the user."""
    from app.workers.tasks.transcribe_call_import_row import (
        _segments_to_user_agent_turns,
    )

    segments = [
        {"speaker": "Speaker 1", "text": "Hello there", "start": 0.0, "end": 1.0},
        {"speaker": "Speaker 2", "text": "Hi back", "start": 1.2, "end": 2.0},
        {"speaker": "Speaker 1", "text": "How can I help", "start": 2.1, "end": 3.0},
    ]
    turns = _segments_to_user_agent_turns(segments)
    assert [t["speaker"] for t in turns] == ["agent", "user", "agent"]
    assert turns[0]["raw_speaker"] == "Speaker 1"
    assert turns[1]["raw_speaker"] == "Speaker 2"


def test_segments_to_user_agent_turns_handles_three_plus_speakers():
    """Speakers beyond the second keep a numbered ``speaker_N`` role so
    multi-party calls never silently lose a participant."""
    from app.workers.tasks.transcribe_call_import_row import (
        _segments_to_user_agent_turns,
    )

    segments = [
        {"speaker": "A", "text": "first", "start": 0.0, "end": 1.0},
        {"speaker": "B", "text": "second", "start": 1.0, "end": 2.0},
        {"speaker": "C", "text": "third", "start": 2.0, "end": 3.0},
    ]
    turns = _segments_to_user_agent_turns(segments)
    assert [t["speaker"] for t in turns] == ["agent", "user", "speaker_3"]


def test_render_turns_as_text_emits_chat_format():
    """The chat-bubble renderer used by both the UI and the CSV export
    emits one ``speaker: text`` line per turn."""
    from app.workers.tasks.transcribe_call_import_row import (
        _render_turns_as_text,
    )

    turns = [
        {"speaker": "agent", "text": "Hello"},
        {"speaker": "user", "text": "Hi"},
    ]
    assert _render_turns_as_text(turns) == "agent: Hello\nuser: Hi"


def test_render_turns_as_text_swap_only_flips_agent_and_user():
    """``swap=True`` flips the agent/user mapping but leaves
    ``speaker_3+`` labels alone (those are real participants outside
    the agent/user duo)."""
    from app.workers.tasks.transcribe_call_import_row import (
        _render_turns_as_text,
    )

    turns = [
        {"speaker": "agent", "text": "a"},
        {"speaker": "user", "text": "u"},
        {"speaker": "speaker_3", "text": "x"},
    ]
    rendered = _render_turns_as_text(turns, swap=True)
    assert rendered == "user: a\nagent: u\nspeaker_3: x"


def test_route_render_diarised_segments_text_matches_worker_format():
    """``_render_diarised_segments_text`` in the route layer must agree
    with the worker's ``_render_turns_as_text`` so swapping at the API
    layer produces the same chat-formatted text the worker originally
    wrote — the UI relies on this contract."""
    from app.api.v1.routes.call_imports import (
        _render_diarised_segments_text,
    )
    from app.workers.tasks.transcribe_call_import_row import (
        _render_turns_as_text,
    )

    segments = [
        {"speaker": "agent", "text": "Hello"},
        {"speaker": "user", "text": "Hi"},
        {"speaker": "speaker_3", "text": "Note"},
    ]
    for swap in (False, True):
        assert _render_diarised_segments_text(
            segments, swap=swap
        ) == _render_turns_as_text(segments, swap=swap)


def test_route_render_diarised_segments_text_skips_bad_entries():
    """Defensive: malformed entries (non-dict / missing keys) are
    dropped silently so a corrupted JSONB row doesn't 500 the route."""
    from app.api.v1.routes.call_imports import (
        _render_diarised_segments_text,
    )

    rendered = _render_diarised_segments_text(
        [
            None,
            "not a dict",
            {"speaker": "agent", "text": "kept"},
            {"speaker": "", "text": "no speaker"},
            {"speaker": "user", "text": ""},
        ]
    )
    assert rendered == "agent: kept"


# ---------------------------------------------------------------------------
# _build_all_columns_block — replaces the removed per-metric input_columns
# ---------------------------------------------------------------------------


def test_build_all_columns_block_renders_every_non_empty_cell():
    from app.workers.tasks.evaluate_call_import_row import (
        _build_all_columns_block,
    )

    raw = {
        "AgentName": "Alice",
        "Empty": "",
        "Notes": "spoke clearly",
    }
    block = _build_all_columns_block(raw, custom_column_mapping=None)
    assert block is not None
    assert "- AgentName: Alice" in block
    assert "- Notes: spoke clearly" in block
    # Empty cells are dropped (no whitespace-only labels in the prompt).
    assert "Empty" not in block


def test_build_all_columns_block_surfaces_friendly_name_alias():
    """When the import defines a friendly-name mapping for a CSV header,
    the prompt shows both identifiers so the LLM can resolve whichever
    name the metric description references."""
    from app.workers.tasks.evaluate_call_import_row import (
        _build_all_columns_block,
    )

    raw = {"Intent_v2": "refund please"}
    mapping = {"customer_intent": "Intent_v2"}
    block = _build_all_columns_block(raw, custom_column_mapping=mapping)
    assert block is not None
    assert "Intent_v2" in block
    assert "customer_intent" in block
    assert "refund please" in block


def test_build_all_columns_block_returns_none_for_empty_row():
    from app.workers.tasks.evaluate_call_import_row import (
        _build_all_columns_block,
    )

    assert _build_all_columns_block({}, custom_column_mapping=None) is None
    assert _build_all_columns_block(None, custom_column_mapping=None) is None


# ---------------------------------------------------------------------------
# Auto-detect comparison metrics from prompt keywords
# ---------------------------------------------------------------------------


def test_metric_text_references_production_detects_keywords():
    """A metric description that mentions any of the well-known
    production / diarised phrases triggers the comparison path."""
    from app.workers.tasks.evaluate_call_import_row import (
        _metric_text_references_production,
    )

    triggering = _make_metric(
        "Diff hunter",
        description="Compare the production transcript with the diarised transcript.",
    )
    plain = _make_metric(
        "Plain",
        description="Score the call's professionalism.",
    )
    assert _metric_text_references_production(triggering) is True
    assert _metric_text_references_production(plain) is False


def test_metric_text_references_production_inherits_from_parent():
    """A child metric inherits comparison mode from its parent's
    description — the parent's prompt is what drives the whole group."""
    from app.workers.tasks.evaluate_call_import_row import (
        _metric_text_references_production,
    )

    child = _make_metric(
        "Yes / No", description="Pick yes or no based on the call."
    )
    parent_with_keyword = _make_metric(
        "Parent",
        description="Compare both transcripts and choose the best label.",
    )
    parent_without_keyword = _make_metric(
        "Parent",
        description="Score the call against the rubric.",
    )

    assert (
        _metric_text_references_production(child, parent=parent_with_keyword)
        is True
    )
    assert (
        _metric_text_references_production(
            child, parent=parent_without_keyword
        )
        is False
    )


def _make_metric(name: str, *, description: str | None = None):
    """Lightweight stub used by the keyword-detection tests above —
    the helper only reads ``name`` / ``description`` off the metric."""
    return SimpleNamespace(
        id=uuid4(), name=name, description=description, metric_type="rating"
    )


# ---------------------------------------------------------------------------
# LLM-based diariser helper
# ---------------------------------------------------------------------------


def test_llm_diariser_parses_bare_json_array(monkeypatch):
    """Happy path: model returns a clean JSON array; the helper
    normalises labels to ``Speaker N`` and assigns monotonically
    increasing synthetic timestamps."""
    from app.workers.tasks.helpers import llm_diarisation

    def _fake_generate_response(**kwargs):
        return {
            "text": (
                '[{"speaker": "agent", "text": "Hi"}, '
                '{"speaker": "user", "text": "Hello"}]'
            )
        }

    monkeypatch.setattr(
        llm_diarisation.llm_service,
        "generate_response",
        _fake_generate_response,
    )

    turns = llm_diarisation.diarize_transcript_with_llm(
        "Hi. Hello.",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=SimpleNamespace(),
    )
    assert [t["speaker"] for t in turns] == ["Speaker 1", "Speaker 2"]
    assert [t["text"] for t in turns] == ["Hi", "Hello"]
    # Synthetic timestamps preserve order for the downstream
    # ``_segments_to_user_agent_turns`` heuristic.
    assert turns[0]["start"] < turns[1]["start"]


def test_llm_diariser_extracts_json_from_markdown_fence(monkeypatch):
    """Chatty models like to wrap JSON in ```json fences; the helper
    must still extract the array."""
    from app.workers.tasks.helpers import llm_diarisation

    monkeypatch.setattr(
        llm_diarisation.llm_service,
        "generate_response",
        lambda **_kw: {
            "text": (
                "Sure, here you go:\n"
                "```json\n"
                '[{"speaker": "Speaker 1", "text": "alpha"},'
                ' {"speaker": "Speaker 2", "text": "beta"}]\n'
                "```\n"
                "Hope this helps!"
            )
        },
    )

    turns = llm_diarisation.diarize_transcript_with_llm(
        "alpha. beta.",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=SimpleNamespace(),
    )
    assert len(turns) == 2
    assert turns[0]["text"] == "alpha"


def test_llm_diariser_raises_on_unparseable_response(monkeypatch):
    from app.workers.tasks.helpers import llm_diarisation

    monkeypatch.setattr(
        llm_diarisation.llm_service,
        "generate_response",
        lambda **_kw: {"text": "I am terribly sorry but I cannot help."},
    )

    with pytest.raises(llm_diarisation.LLMDiarisationError):
        llm_diarisation.diarize_transcript_with_llm(
            "x",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            organization_id=uuid4(),
            db=SimpleNamespace(),
        )


def test_llm_diariser_rejects_unknown_provider():
    from app.workers.tasks.helpers import llm_diarisation

    with pytest.raises(llm_diarisation.LLMDiarisationError):
        llm_diarisation.diarize_transcript_with_llm(
            "x",
            llm_provider="not-a-real-provider",
            llm_model="anything",
            organization_id=uuid4(),
            db=SimpleNamespace(),
        )


def test_llm_diariser_short_circuits_on_empty_transcript():
    from app.workers.tasks.helpers import llm_diarisation

    assert (
        llm_diarisation.diarize_transcript_with_llm(
            "   ",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            organization_id=uuid4(),
            db=SimpleNamespace(),
        )
        == []
    )


def test_llm_diariser_falls_back_to_default_prompt(monkeypatch):
    """Empty / whitespace custom prompt routes through the canonical
    default so the operator always gets a usable diariser even when
    they don't fill the textarea."""
    from app.workers.tasks.helpers import llm_diarisation

    captured: dict = {}

    def _fake_generate_response(**kwargs):
        captured["messages"] = kwargs["messages"]
        return {"text": '[{"speaker": "agent", "text": "Hi"}]'}

    monkeypatch.setattr(
        llm_diarisation.llm_service,
        "generate_response",
        _fake_generate_response,
    )

    llm_diarisation.diarize_transcript_with_llm(
        "Hi.",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=SimpleNamespace(),
        custom_prompt="   ",
    )

    system_msg = captured["messages"][0]
    assert system_msg["role"] == "system"
    assert system_msg["content"] == llm_diarisation.DEFAULT_DIARIZATION_PROMPT


def test_llm_diariser_normalises_label_aliases(monkeypatch):
    """The model may return human-friendly labels like ``customer``;
    the helper coerces them onto the canonical ``Speaker N`` track
    that the downstream first-speaker-is-agent heuristic understands."""
    from app.workers.tasks.helpers import llm_diarisation

    monkeypatch.setattr(
        llm_diarisation.llm_service,
        "generate_response",
        lambda **_kw: {
            "text": (
                '[{"speaker": "Customer", "text": "Hi"},'
                ' {"speaker": "Agent", "text": "Hello"}]'
            )
        },
    )

    turns = llm_diarisation.diarize_transcript_with_llm(
        "Hi. Hello.",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=SimpleNamespace(),
    )
    raw_speakers = [t["speaker"] for t in turns]
    # ``customer`` -> ``Speaker 2``, ``agent`` -> ``Speaker 1``. The
    # downstream mapper then sorts by start time and re-labels the
    # earliest turn as agent / next as user, but that's a separate
    # concern; here we only confirm the label normalisation is sane.
    assert raw_speakers == ["Speaker 2", "Speaker 1"]


# ---------------------------------------------------------------------------
# Diariser-prompt default endpoint
# ---------------------------------------------------------------------------


def test_diarisation_prompt_default_endpoint_returns_canonical_constant():
    """The GET endpoint must return the exact constant the worker
    falls back to so the UI's pre-filled textarea matches the
    server-side default verbatim."""
    import asyncio

    from app.api.v1.routes.call_imports import (
        get_call_import_diarisation_prompt_default,
    )
    from app.workers.tasks.helpers.llm_diarisation import (
        DEFAULT_DIARIZATION_PROMPT,
    )

    response = asyncio.run(
        get_call_import_diarisation_prompt_default(
            api_key="ignored", organization_id=uuid4()
        )
    )
    assert response.prompt == DEFAULT_DIARIZATION_PROMPT


# ---------------------------------------------------------------------------
# Transcribe request schema validation
# ---------------------------------------------------------------------------


def test_transcribe_request_requires_llm_diariser_fields():
    """The Pydantic schema rejects payloads that omit
    ``diarization_llm_provider`` / ``diarization_llm_model`` so the
    modal can't accidentally submit an incomplete request."""
    from pydantic import ValidationError

    from app.models.schemas import CallImportTranscribeRequest

    # Both required fields present — passes.
    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
    )
    assert payload.diarization_llm_provider == "openai"

    # Missing diariser model — rejected.
    with pytest.raises(ValidationError):
        CallImportTranscribeRequest(
            stt_provider="deepgram",
            stt_model="nova-2",
            diarization_llm_provider="openai",
        )
