"""Tests for the evaluate_call_import_row Celery task and its rollup helper."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Organization,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


class _NonClosingSession:
    """Session proxy that ignores .close() so the test can still inspect rows
    after the Celery task wraps everything in a try/finally that closes the DB.
    """

    def __init__(self, session):
        self._session = session

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._session, name)


def _seed(db_session, *, row_count: int = 1, metric_count: int = 1):
    org = Organization(id=uuid4(), name="Eval Test Org")
    db_session.add(org)
    workspace = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add(workspace)
    db_session.commit()

    metrics = []
    for i in range(metric_count):
        metric = Metric(
            id=uuid4(),
            organization_id=org.id,
            workspace_id=workspace.id,
            name=f"Metric{i}",
            description=f"Metric {i}",
            metric_type="rating",
            trigger="always",
            enabled=True,
            supported_surfaces=["agent"],
            enabled_surfaces=["agent"],
        )
        db_session.add(metric)
        metrics.append(metric)

    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        provider="exotel",
        original_filename="batch.csv",
        total_rows=row_count,
        completed_rows=row_count,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    source_rows = []
    for idx in range(row_count):
        transcript = f"Hello transcript {idx}"
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org.id,
            row_index=idx,
            conversation_id=f"call-{idx}",
            transcript=transcript,
            diarised_transcript=transcript,
            status=CallImportRowStatus.COMPLETED,
        )
        db_session.add(row)
        source_rows.append(row)

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=workspace.id,
        selected_metric_ids=[str(m.id) for m in metrics],
        status="pending",
        total_rows=row_count,
        completed_rows=0,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.flush()

    eval_rows = []
    for row in source_rows:
        er = CallImportEvaluationRow(
            id=uuid4(),
            evaluation_id=evaluation.id,
            call_import_row_id=row.id,
            status="pending",
            metric_scores={},
        )
        db_session.add(er)
        eval_rows.append(er)
    db_session.commit()

    return org, call_import, metrics, source_rows, evaluation, eval_rows


def _patch_dependencies(monkeypatch, db_session, *, evaluate_with_llm=None):
    """Stub SessionLocal and the LLM helper inside the eval task module."""
    from app.workers.tasks import evaluate_call_import_row as task_module

    monkeypatch.setattr(
        task_module, "SessionLocal", lambda: _NonClosingSession(db_session)
    )

    def _default_eval(*_args, **_kwargs):
        metrics = _kwargs.get("llm_metrics") or (_args[1] if len(_args) > 1 else [])
        scores = {
            str(metric.id): {
                "value": 4,
                "type": "rating",
                "metric_name": metric.name,
            }
            for metric in metrics
        }
        return scores, 0.42

    monkeypatch.setattr(
        task_module,
        "evaluate_with_llm",
        evaluate_with_llm or _default_eval,
    )

    return task_module


def test_evaluate_call_import_row_happy_path(db_session, monkeypatch):
    _, _ci, metrics, _source_rows, evaluation, eval_rows = _seed(db_session)
    eval_row = eval_rows[0]

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(eval_row.id))

    assert result["status"] == "completed"

    db_session.refresh(eval_row)
    db_session.refresh(evaluation)

    assert eval_row.status == "completed"
    assert eval_row.error_message is None
    assert str(metrics[0].id) in (eval_row.metric_scores or {})
    assert eval_row.metric_scores[str(metrics[0].id)]["value"] == 4

    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 0
    assert evaluation.status == "completed"
    assert evaluation.finished_at is not None


def test_evaluate_call_import_row_honors_metric_subset(db_session, monkeypatch):
    """When the evaluation selects a subset of metrics, only those are scored."""
    _, _ci, metrics, _rows, evaluation, eval_rows = _seed(
        db_session, metric_count=3
    )

    # Restrict the evaluation to just the first two metrics.
    selected = metrics[:2]
    evaluation.selected_metric_ids = [str(m.id) for m in selected]
    db_session.commit()

    received_metric_ids = {}

    def _capture_eval(*_a, **kw):
        llm_metrics = kw["llm_metrics"]
        received_metric_ids["ids"] = {str(m.id) for m in llm_metrics}
        return (
            {
                str(m.id): {"value": 3, "type": "rating", "metric_name": m.name}
                for m in llm_metrics
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture_eval
    )
    task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert received_metric_ids["ids"] == {str(m.id) for m in selected}
    db_session.refresh(eval_rows[0])
    assert set(eval_rows[0].metric_scores.keys()) == {str(m.id) for m in selected}


def test_evaluate_call_import_row_marks_failed_on_empty_transcript(
    db_session, monkeypatch
):
    _, _ci, _metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    source_rows[0].transcript = "   "
    source_rows[0].diarised_transcript = None
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "failed"
    assert result["reason"] == "missing_transcript"

    db_session.refresh(eval_rows[0])
    db_session.refresh(evaluation)
    assert eval_rows[0].status == "failed"
    # Normal metrics always require a diarised transcript.
    err = (eval_rows[0].error_message or "").lower()
    assert "transcript" in err
    assert "diarised" in err
    assert evaluation.failed_rows == 1
    assert evaluation.completed_rows == 0
    assert evaluation.status == "failed"


def test_evaluate_call_import_row_partial_when_mixed_outcomes(db_session, monkeypatch):
    """If sibling rows are already failed, the rollup should land on 'partial'."""
    _, _ci, _metrics, _source_rows, evaluation, eval_rows = _seed(
        db_session, row_count=2
    )
    # Pre-mark the second eval row as failed.
    eval_rows[1].status = "failed"
    eval_rows[1].error_message = "previous failure"
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    db_session.refresh(evaluation)
    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 1
    assert evaluation.status == "partial"


def test_evaluate_call_import_row_handles_llm_exception(db_session, monkeypatch):
    _, _ci, _metrics, _rows, evaluation, eval_rows = _seed(db_session)

    def _raise(*_a, **_kw):
        raise RuntimeError("LLM blew up")

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_raise
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))
    assert result["status"] == "failed"

    db_session.refresh(eval_rows[0])
    db_session.refresh(evaluation)
    assert eval_rows[0].status == "failed"
    assert "LLM blew up" in (eval_rows[0].error_message or "")
    assert evaluation.status == "failed"


def test_evaluate_call_import_row_handles_missing_row(db_session, monkeypatch):
    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(uuid4()))
    assert result["status"] == "skipped"
    assert result["reason"] == "row_not_found"


def test_evaluate_call_import_row_reads_diarised_when_source_is_diarised(
    db_session, monkeypatch
):
    """When the parent evaluation's ``transcript_source = 'diarised'`` the
    worker must hand the diarised transcript (not the CSV production
    transcript) to the LLM helper."""
    _, _ci, _metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    # CSV transcript is set by _seed; populate the diarised column with
    # something distinguishable and flip the parent eval to 'diarised'.
    source_rows[0].diarised_transcript = "DIARISED ONLY VALUE"
    evaluation.transcript_source = "diarised"
    db_session.commit()

    captured: dict = {}

    def _capture(*_args, **kwargs):
        captured["transcription"] = kwargs.get("transcription")
        llm_metrics = kwargs["llm_metrics"]
        return (
            {
                str(m.id): {
                    "value": 5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in llm_metrics
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "completed"
    assert captured["transcription"] == "DIARISED ONLY VALUE"


def test_evaluate_call_import_row_fails_when_diarised_transcript_missing(
    db_session, monkeypatch
):
    """A diarised-source evaluation must skip+fail rows whose
    ``diarised_transcript`` is empty (with a clear error message)."""
    _, _ci, _metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    source_rows[0].transcript = "production has text"
    source_rows[0].diarised_transcript = None
    evaluation.transcript_source = "diarised"
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "failed"
    assert result["reason"] == "missing_transcript"

    db_session.refresh(eval_rows[0])
    err = (eval_rows[0].error_message or "").lower()
    assert "diarised" in err
    assert "transcript" in err


# ---------------------------------------------------------------------------
# The legacy "column-input judge" feature (``Metric.input_columns``)
# was removed in favour of always injecting EVERY non-empty CSV column
# into the evaluation prompt for every metric (see
# ``_build_all_columns_block`` in ``evaluate_call_import_row``). The
# tests that exercised the per-metric column allow-list were dropped
# with the feature; ``test_evaluate_call_import_row_injects_all_columns_block``
# below covers the replacement behaviour.
# ---------------------------------------------------------------------------


def test_evaluate_call_import_row_injects_all_columns_block(
    db_session, monkeypatch
):
    """Every LLM evaluation receives an ``all_columns_block`` containing
    EVERY non-empty raw column from the source row, regardless of the
    metric's definition. Covers the replacement for the removed
    ``Metric.input_columns`` allow-list."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    source_rows[0].raw_columns = {
        "customer_intent": "refund please",
        "agent_response": "approved",
        "blank_col": "",
        "unrelated": "noise",
    }
    db_session.commit()

    captured: dict = {}

    def _capture(*_args, **kwargs):
        captured["all_columns_block"] = kwargs.get("all_columns_block")
        captured["transcription"] = kwargs.get("transcription")
        return (
            {
                str(m.id): {
                    "value": 4,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))
    assert result["status"] == "completed"

    block = captured["all_columns_block"] or ""
    # Every non-empty column is rendered as ``- <header>: <value>``.
    assert "- customer_intent: refund please" in block
    assert "- agent_response: approved" in block
    assert "- unrelated: noise" in block
    # Empty cells are dropped.
    assert "blank_col" not in block
    # The transcript is still passed alongside so the metric is scored
    # against the conversation, not the columns.
    assert captured["transcription"] == "Hello transcript 0"
    db_session.refresh(eval_rows[0])
    assert str(metric.id) in (eval_rows[0].metric_scores or {})


# ---------------------------------------------------------------------------
# Transcript-compare judge metrics (Metric.compare_transcripts)
# ---------------------------------------------------------------------------


def _make_categorize_metric(
    name: str,
    *,
    compare_transcripts: bool = False,
    description: str | None = None,
    parent_metric_id=None,
):
    """Lightweight duck-typed Metric for the pure ``_categorize_metrics``
    helper tests (no DB, no SQLAlchemy session)."""
    from types import SimpleNamespace
    from uuid import uuid4

    return SimpleNamespace(
        id=uuid4(),
        name=name,
        metric_type="rating",
        compare_transcripts=compare_transcripts,
        description=description,
        parent_metric_id=parent_metric_id,
    )


def test_categorize_metrics_buckets_comparison_metric_when_both_transcripts_present():
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    cmp_metric = _make_categorize_metric(
        "Transcript Fidelity", compare_transcripts=True
    )
    regular = _make_categorize_metric("Regular")

    (
        transcript_metrics,
        audio_metrics,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [cmp_metric, regular],
        has_audio=False,
        has_production_transcript=True,
        has_diarised_transcript=True,
    )

    assert [m.id for m in comparison_metrics] == [cmp_metric.id]
    assert [m.id for m in transcript_metrics] == [regular.id]
    assert audio_metrics == []
    assert skipped == {}


def test_categorize_metrics_skips_comparison_metric_when_production_missing():
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    cmp_metric = _make_categorize_metric(
        "Transcript Fidelity", compare_transcripts=True
    )
    (
        transcript_metrics,
        _audio,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [cmp_metric],
        has_audio=False,
        has_production_transcript=False,
        has_diarised_transcript=True,
    )

    assert comparison_metrics == []
    assert transcript_metrics == []
    entry = skipped[str(cmp_metric.id)]
    assert entry["skipped"] == "comparison_missing_transcript"
    assert entry["missing_transcripts"] == ["production"]
    assert entry["value"] is None
    assert entry["metric_name"] == "Transcript Fidelity"


def test_categorize_metrics_skips_comparison_metric_when_both_transcripts_missing():
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    cmp_metric = _make_categorize_metric(
        "Transcript Fidelity", compare_transcripts=True
    )
    (
        _transcript_metrics,
        _audio,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [cmp_metric],
        has_audio=False,
        has_production_transcript=False,
        has_diarised_transcript=False,
    )

    assert comparison_metrics == []
    entry = skipped[str(cmp_metric.id)]
    assert entry["skipped"] == "comparison_missing_transcript"
    # Order is deterministic (production checked first), so both labels
    # appear when both sides are empty.
    assert entry["missing_transcripts"] == ["production", "diarised"]


def test_categorize_metrics_auto_promotes_standalone_when_description_references_production():
    """Standalone metric whose description mentions the production /
    diarised transcripts is routed to the comparison bucket even
    without the explicit ``compare_transcripts`` flag."""
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    auto_compare = _make_categorize_metric(
        "Diff Hunter",
        description="Compare the production transcript with the diarised transcript.",
    )
    plain = _make_categorize_metric(
        "Plain", description="Score the call's professionalism."
    )

    (
        transcript_metrics,
        _audio,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [auto_compare, plain],
        has_audio=False,
        has_production_transcript=True,
        has_diarised_transcript=True,
    )

    assert [m.id for m in comparison_metrics] == [auto_compare.id]
    assert [m.id for m in transcript_metrics] == [plain.id]
    assert skipped == {}


def test_evaluate_call_import_row_scores_comparison_metric_with_both_transcripts(
    db_session, monkeypatch
):
    """Happy path: a comparison metric on a row with both transcripts
    calls evaluate_with_llm exactly once and forwards the labeled
    transcript pair via the ``comparison_pair`` kwarg."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.compare_transcripts = True
    source_rows[0].transcript = "PROD speak"
    source_rows[0].diarised_transcript = "DIAR speak"
    db_session.commit()

    captured: list[dict] = []

    def _capture(*_args, **kwargs):
        captured.append(
            {
                "transcription": kwargs.get("transcription"),
                "comparison_pair": kwargs.get("comparison_pair"),
                "metric_ids": [str(m.id) for m in kwargs["llm_metrics"]],
            }
        )
        return (
            {
                str(m.id): {
                    "value": 0.85,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.12,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "completed"
    assert len(captured) == 1
    invocation = captured[0]
    assert invocation["metric_ids"] == [str(metric.id)]
    # Comparison metrics intentionally pass an empty transcription
    # because the prompt-builder reads the pair via ``comparison_pair``.
    assert invocation["transcription"] == ""
    assert invocation["comparison_pair"] == ("PROD speak", "DIAR speak")


def test_evaluate_call_import_row_records_comparison_skip_when_diarised_missing(
    db_session, monkeypatch
):
    """A comparison metric on a row with only the production transcript
    is skipped (not hard-failed) so neighboring metrics can still score
    cleanly. When it's the only metric on the row the run hard-fails
    with ``no_evaluable_metrics`` — same shape as the column-input
    skip-only case."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.compare_transcripts = True
    source_rows[0].transcript = "PROD only"
    source_rows[0].diarised_transcript = None
    db_session.commit()

    llm_called = {"hit": False}

    def _capture(*_args, **_kwargs):
        llm_called["hit"] = True
        return ({}, 0.0)

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "failed"
    assert result["reason"] == "no_evaluable_metrics"
    assert llm_called["hit"] is False

    db_session.refresh(eval_rows[0])
    entry = eval_rows[0].metric_scores[str(metric.id)]
    assert entry["value"] is None
    assert entry["skipped"] == "comparison_missing_transcript"
    assert entry["missing_transcripts"] == ["diarised"]
    assert entry["metric_name"] == metric.name


def test_evaluate_call_import_row_mixes_comparison_with_other_metric_kinds(
    db_session, monkeypatch
):
    """A run can mix comparison + transcript metrics in one row. Each
    metric is dispatched to its own bucket and the row completes once
    every bucket has either a score or a skip entry."""
    _, _ci, metrics, source_rows, evaluation, eval_rows = _seed(
        db_session, metric_count=2
    )
    transcript_metric, comparison_metric = metrics
    comparison_metric.compare_transcripts = True
    source_rows[0].transcript = "PROD text"
    source_rows[0].diarised_transcript = "DIAR text"
    # Pin the run to diarised so the transcript-metric assertion below
    # is explicit; normal metrics always read diarised_transcript.
    evaluation.transcript_source = "diarised"
    db_session.commit()

    invocations: list[dict] = []

    def _capture(*_args, **kwargs):
        invocations.append(
            {
                "metric_ids": [str(m.id) for m in kwargs["llm_metrics"]],
                "transcription": kwargs.get("transcription"),
                "comparison_pair": kwargs.get("comparison_pair"),
            }
        )
        return (
            {
                str(m.id): {
                    "value": 1,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )
    assert result["status"] == "completed"

    # Two LLM invocations: one per kind (comparison, transcript).
    # Ordering is implementation-defined so key by metric.
    assert len(invocations) == 2
    by_metric = {inv["metric_ids"][0]: inv for inv in invocations}

    cmp_call = by_metric[str(comparison_metric.id)]
    assert cmp_call["transcription"] == ""
    assert cmp_call["comparison_pair"] == ("PROD text", "DIAR text")

    transcript_call = by_metric[str(transcript_metric.id)]
    assert transcript_call["comparison_pair"] is None
    assert transcript_call["transcription"] == "DIAR text"

    db_session.refresh(eval_rows[0])
    # Both metrics scored exactly once; the column-input bucket has
    # been removed alongside ``Metric.input_columns``.
    assert set(eval_rows[0].metric_scores.keys()) == {
        str(transcript_metric.id),
        str(comparison_metric.id),
    }


def test_evaluate_call_import_row_ignores_transcript_source_for_comparison_metrics(
    db_session, monkeypatch
):
    """The run's ``transcript_source`` setting must NOT affect what a
    comparison metric reads — it always receives both transcripts as a
    labeled pair regardless of which source the parent evaluation picked."""
    _, _ci, metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.compare_transcripts = True
    source_rows[0].transcript = "PROD text"
    source_rows[0].diarised_transcript = "DIAR text"
    # Flip the run to diarised so the legacy transcript bucket would
    # normally read from ``diarised_transcript``. Comparison metrics
    # ignore this — both sides are still passed to the LLM.
    evaluation.transcript_source = "diarised"
    db_session.commit()

    captured: list[dict] = []

    def _capture(*_args, **kwargs):
        captured.append(
            {
                "comparison_pair": kwargs.get("comparison_pair"),
                "transcription": kwargs.get("transcription"),
            }
        )
        return (
            {
                str(m.id): {
                    "value": 0.5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.05,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "completed"
    assert len(captured) == 1
    # Pair order is (production, diarised) — fixed by the worker, not
    # by the run's transcript_source toggle.
    assert captured[0]["comparison_pair"] == ("PROD text", "DIAR text")
    assert captured[0]["transcription"] == ""


# ---------------------------------------------------------------------------
# Cancelled-mid-flight guard
# ---------------------------------------------------------------------------
#
# When the operator hits the cancel endpoint while a worker is mid-LLM call,
# the API flips the row to ``failed`` + the cancelled-by-user sentinel BEFORE
# revoking the Celery task. If the worker happens to finish its call before
# the SIGTERM lands, it would race the API and overwrite the cancelled state
# with its own terminal status / scores. The ``_was_cancelled_externally``
# guard re-reads the row right before the terminal write so the cancel wins.


def test_evaluate_call_import_row_skips_terminal_write_when_cancelled(
    db_session, monkeypatch
):
    """If the row was flipped to the cancelled sentinel between the worker's
    initial ``running`` write and the final terminal write, the worker must
    NOT overwrite ``status`` / ``error_message`` / ``metric_scores`` with its
    own success values — the operator's cancel wins the race."""
    _, _ci, _metrics, _source_rows, evaluation, eval_rows = _seed(db_session)
    eval_row = eval_rows[0]

    # Fire the cancel via ``evaluate_with_llm``: the helper runs AFTER the
    # worker has already written ``status='running'`` but BEFORE the final
    # terminal write, which is exactly the race window the guard is meant
    # to protect. The simulated cancel mirrors what
    # ``_apply_evaluation_cancel`` would do server-side.
    def _simulate_cancel(*_args, **kwargs):
        # Round-trip through the DB so the worker's session must
        # ``expire`` + ``refresh`` to see the flipped state — that's
        # the actual code path under test.
        from sqlalchemy import update

        db_session.execute(
            update(CallImportEvaluationRow)
            .where(CallImportEvaluationRow.id == eval_row.id)
            .values(
                status="failed",
                error_message="Evaluation cancelled by user",
                celery_task_id=None,
            )
        )
        db_session.commit()
        # Return a normal "scored" payload so the worker would otherwise
        # try to write ``completed`` + these scores onto the row; the
        # guard should prevent that.
        metrics = kwargs.get("llm_metrics") or []
        return (
            {
                str(m.id): {"value": 5, "type": "rating", "metric_name": m.name}
                for m in metrics
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_simulate_cancel
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_row.id))

    # Guard surfaces a typed ``cancelled`` short-circuit so the caller
    # (Celery's group rollup) can tell the row didn't fail organically.
    assert result["status"] == "cancelled"

    db_session.expire_all()
    refreshed = db_session.get(CallImportEvaluationRow, eval_row.id)
    # Cancel sentinel is preserved verbatim — the worker did NOT overwrite
    # ``status`` to ``completed`` and did NOT stamp the synthetic scores
    # the LLM stub returned.
    assert refreshed.status == "failed"
    assert refreshed.error_message == "Evaluation cancelled by user"
    assert refreshed.metric_scores in (None, {}, {} or None)

    # Parent rollup still ran, so its counters reflect the cancelled row.
    refreshed_eval = db_session.get(CallImportEvaluation, evaluation.id)
    assert refreshed_eval.failed_rows == 1
    assert refreshed_eval.completed_rows == 0
