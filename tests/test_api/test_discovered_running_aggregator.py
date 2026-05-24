"""Tests for ``_get_running_discovered_labels`` aggregator.

The aggregator powers two surfaces with the same data: the worker's
prompt-stuffing ("REUSE existing discovered keys") and the
``GET /discovered-labels`` API. Both flatten the per-row JSON
``metric_scores[parent_id].discovered_labels`` payload, slug-dedupe by
key, count occurrences, and keep the first non-empty rationale.
"""

from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import (
    _get_running_discovered_labels,
)
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Workspace,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
)


def _ensure_default_workspace(db_session, org_id):
    ws = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    if ws is None:
        ws = Workspace(
            organization_id=org_id, name="Default", slug="default", is_default=True
        )
        db_session.add(ws)
        db_session.commit()
    return ws


def _seed_call_import_and_eval(db_session, org_id):
    workspace = _ensure_default_workspace(db_session, org_id)
    ci = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        column_mapping={},
        extra_columns=[],
        custom_column_mapping={},
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(ci)
    db_session.commit()
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=ci.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Run 1",
        selected_metric_ids=[],
        status="completed",
    )
    db_session.add(evaluation)
    db_session.commit()
    return ci, evaluation


_row_counter = {"n": 0}


def _add_eval_row(
    db_session,
    *,
    evaluation,
    call_import,
    metric_scores,
    status=CallImportRowStatus.COMPLETED.value,
):
    _row_counter["n"] += 1
    source = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        row_index=_row_counter["n"],
        conversation_id=f"call-{_row_counter['n']}",
        raw_columns={},
    )
    db_session.add(source)
    db_session.flush()
    row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=source.id,
        status=status,
        metric_scores=metric_scores,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_aggregator_slug_dedupes_across_rows_and_counts(db_session, org_id, seed_org):
    parent_id = uuid4()
    call_import, evaluation = _seed_call_import_and_eval(db_session, org_id)

    # Row 1: 'Customer On Hold' with a rationale.
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            str(parent_id): {
                "discovered_labels": [
                    {
                        "key": "Customer On Hold",
                        "name": "Customer on hold",
                        "description": "caller paused",
                        "rationale": "Please hold a moment",
                    }
                ]
            }
        },
    )
    # Row 2: same slug (different casing), no description/rationale.
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            str(parent_id): {
                "discovered_labels": [
                    {"key": "customer_on_hold", "name": "On hold"}
                ]
            }
        },
    )
    # Row 3: a distinct discovered slug.
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            str(parent_id): {
                "discovered_labels": [
                    {
                        "key": "pitch_never_happened",
                        "name": "Pitch never happened",
                    }
                ]
            }
        },
    )

    items = _get_running_discovered_labels(
        db_session, evaluation.id, parent_id
    )
    by_key = {item["key"]: item for item in items}
    assert set(by_key.keys()) == {"customer_on_hold", "pitch_never_happened"}
    assert by_key["customer_on_hold"]["count"] == 2
    # Description + rationale survive across rows even when the second
    # occurrence omitted them.
    assert by_key["customer_on_hold"]["description"] == "caller paused"
    assert by_key["customer_on_hold"]["sample_rationale"] == "Please hold a moment"
    # Result is ordered by descending count then key.
    assert items[0]["key"] == "customer_on_hold"


def test_aggregator_ignores_non_completed_rows(db_session, org_id, seed_org):
    parent_id = uuid4()
    call_import, evaluation = _seed_call_import_and_eval(db_session, org_id)

    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        status="running",
        metric_scores={
            str(parent_id): {
                "discovered_labels": [
                    {"key": "in_flight_label", "name": "In flight"}
                ]
            }
        },
    )

    items = _get_running_discovered_labels(
        db_session, evaluation.id, parent_id
    )
    assert items == []


def test_aggregator_returns_empty_when_no_discovered_payload(
    db_session, org_id, seed_org
):
    parent_id = uuid4()
    call_import, evaluation = _seed_call_import_and_eval(db_session, org_id)
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={str(parent_id): {"sequence": ["x"]}},
    )
    items = _get_running_discovered_labels(
        db_session, evaluation.id, parent_id
    )
    assert items == []


def test_aggregator_collects_up_to_three_distinct_rationales(
    db_session, org_id, seed_org
):
    """Multiple rows producing the same discovered slug should fold their
    rationales into ``examples`` (capped at 3, de-duplicated, preserving
    order). Powers the Promote auto-fill flow that pre-populates the
    new sub-metric's rubric with concrete examples.
    """

    parent_id = uuid4()
    call_import, evaluation = _seed_call_import_and_eval(db_session, org_id)

    rationales = [
        "Customer asked to be put on hold",
        "  customer asked to be put on hold  ",  # duplicate by trim/case
        "Hold music played",
        "Agent asked them to wait",
        # Fifth distinct rationale -- should be dropped (cap is 3).
        "Caller said 'please hold'",
    ]
    for rationale in rationales:
        _add_eval_row(
            db_session,
            evaluation=evaluation,
            call_import=call_import,
            metric_scores={
                str(parent_id): {
                    "discovered_labels": [
                        {
                            "key": "customer_on_hold",
                            "name": "Customer on hold",
                            "rationale": rationale,
                        }
                    ]
                }
            },
        )

    items = _get_running_discovered_labels(
        db_session, evaluation.id, parent_id
    )
    by_key = {item["key"]: item for item in items}
    entry = by_key["customer_on_hold"]
    examples = entry["examples"]

    assert entry["count"] == 5
    assert len(examples) == 3
    # First three distinct rationales are kept in order; the
    # whitespace/case duplicate of #1 is dropped.
    assert examples[0] == "Customer asked to be put on hold"
    assert examples[1] == "Hold music played"
    assert examples[2] == "Agent asked them to wait"
    # The aggregator-level back-compat field still points at the
    # first non-empty rationale.
    assert entry["sample_rationale"] == "Customer asked to be put on hold"


def test_aggregator_omits_examples_when_no_rationales(db_session, org_id, seed_org):
    parent_id = uuid4()
    call_import, evaluation = _seed_call_import_and_eval(db_session, org_id)

    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            str(parent_id): {
                "discovered_labels": [
                    {"key": "no_rationale_label", "name": "Quiet label"}
                ]
            }
        },
    )

    items = _get_running_discovered_labels(
        db_session, evaluation.id, parent_id
    )
    entry = next(i for i in items if i["key"] == "no_rationale_label")
    assert entry["examples"] == []
    assert entry["sample_rationale"] is None
