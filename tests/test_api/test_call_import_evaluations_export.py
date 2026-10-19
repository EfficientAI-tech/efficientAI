"""Integration tests for the call-import evaluation CSV export endpoint.

Focuses on the ``capture_rationale`` column-doubling behavior:

* metrics with ``capture_rationale = True`` add a sibling
  ``"<Name> - LLM Rationale"`` column populated from
  ``metric_scores[id].rationale``;
* metrics without it keep their single ``"<Name>"`` value column
  (preserving the existing export shape for old metrics / old runs).
"""

from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus, MetricType, MetricTrigger


def _ensure_default_workspace(db_session, org_id):
    """Tests bypass the migration, so seed the per-org Default workspace
    on demand. The first call creates it; subsequent calls reuse it."""
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


def _make_call_import(db_session, org_id, *, custom_columns=None):
    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        original_filename="test.csv",
        column_mapping={
            "external_call_id": "CallID",
            "transcript": "Transcript",
            "recording_url": "Recording URL",
        },
        extra_columns=[],
        custom_column_mapping=custom_columns or {},
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.commit()
    return call_import


def _make_audio_call_import(db_session, org_id):
    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider=None,
        original_filename="sales call.wav",
        source_format="audio",
        column_mapping={},
        extra_columns=[],
        custom_column_mapping={},
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.commit()
    return call_import


def _make_audio_call_import_row(
    db_session, call_import, *, conversation_id="sales_call", row_index=0
):
    row = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        row_index=row_index,
        conversation_id=conversation_id,
        recording_url=None,
        transcript="hello world",
        raw_columns={"conversation_id": conversation_id},
        status=CallImportRowStatus.COMPLETED,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _make_call_import_row(db_session, call_import, row_index=0, raw_columns=None):
    row = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        row_index=row_index,
        conversation_id=f"call-{row_index}",
        recording_url="https://x/r.mp3",
        transcript="hello world",
        raw_columns=raw_columns
        or {
            "CallID": f"call-{row_index}",
            "Recording URL": "https://x/r.mp3",
            "Transcript": "hello world",
        },
        status=CallImportRowStatus.COMPLETED,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _make_metric(
    db_session,
    org_id,
    *,
    name,
    capture_rationale=False,
    custom_data_type=None,
    custom_config=None,
    metric_type=MetricType.RATING.value,
):
    workspace = _ensure_default_workspace(db_session, org_id)
    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        name=name,
        description=f"Evaluate {name}",
        metric_type=metric_type,
        trigger=MetricTrigger.ALWAYS.value,
        enabled=True,
        is_default=False,
        custom_data_type=custom_data_type,
        custom_config=custom_config,
        capture_rationale=capture_rationale,
    )
    db_session.add(metric)
    db_session.commit()
    return metric


def _make_evaluation_with_row(
    db_session,
    *,
    call_import,
    source_row,
    metrics,
    metric_scores,
):
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        workspace_id=call_import.workspace_id,
        name="QA pass",
        selected_metric_ids=[str(m.id) for m in metrics],
        status="completed",
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.commit()

    eval_row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=source_row.id,
        status="completed",
        metric_scores=metric_scores,
    )
    db_session.add(eval_row)
    db_session.commit()
    return evaluation


def _parse_csv(body: bytes) -> tuple[list[str], list[dict[str, str]]]:
    import csv as csv_module
    import io as io_module

    text = body.decode("utf-8-sig")
    reader = csv_module.DictReader(io_module.StringIO(text))
    return list(reader.fieldnames or []), list(reader)


class _ExportBody:
    def __init__(self, content: bytes, content_type: str, disposition: str):
        self.content = content
        self.status_code = 200
        self.headers = {
            "content-type": content_type,
            "content-disposition": disposition,
        }
        if content_type.startswith("text/"):
            self.text = content.decode("utf-8-sig")
        else:
            self.text = ""


def _render_export(
    db_session,
    call_import,
    evaluation,
    *,
    include_transcripts=True,
    format="csv",
):
    """Column checks call the projector. Delivery is covered by the job tests."""
    from app.services.call_imports.evaluation_export import (
        render_export_csv_bytes,
        render_export_xlsx_bytes,
    )

    if format == "xlsx":
        content = render_export_xlsx_bytes(db_session, call_import, evaluation)
        return _ExportBody(
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            'attachment; filename="export.xlsx"',
        )
    content = render_export_csv_bytes(
        db_session,
        call_import,
        evaluation,
        include_transcripts=include_transcripts,
    )
    return _ExportBody(
        content,
        "text/csv; charset=utf-8-sig",
        'attachment; filename="export.csv"',
    )


def test_export_emits_rationale_column_for_capture_rationale_metric(
    authenticated_client, db_session, org_id, seed_org
):
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)

    enum_metric = _make_metric(
        db_session,
        org_id,
        name="Pitch Type",
        capture_rationale=True,
        custom_data_type="enum",
        custom_config={"options": ["WITH data", "WITHOUT data"]},
    )

    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[enum_metric],
        metric_scores={
            str(enum_metric.id): {
                "value": "WITH data",
                "type": "enum",
                "metric_name": "Pitch Type",
                "options": ["WITH data", "WITHOUT data"],
                "rationale": "Agent referenced 120 percent growth in turn 1.",
            }
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    headers, rows = _parse_csv(response.content)

    assert "Pitch Type" in headers
    assert "Pitch Type - LLM Rationale" in headers
    # The rationale column must come immediately after its value column so
    # the user's downloaded CSV mirrors the on-screen table.
    assert headers.index("Pitch Type - LLM Rationale") == headers.index("Pitch Type") + 1

    # Three new fixed columns surface both transcripts and the run's
    # transcript_source side-by-side. They sit before the metric columns
    # so the export reads like "context → metrics".
    assert "Production Transcript" in headers
    assert "Diarised Transcript" in headers
    assert "Evaluated Transcript Source" in headers
    assert headers.index("Production Transcript") < headers.index("Pitch Type")
    assert headers.index("Diarised Transcript") < headers.index("Pitch Type")
    assert headers.index("Evaluated Transcript Source") < headers.index("Pitch Type")

    assert len(rows) == 1
    assert rows[0]["Pitch Type"] == "WITH data"
    assert rows[0]["Pitch Type - LLM Rationale"].startswith("Agent referenced")
    assert rows[0]["Production Transcript"] == "hello world"
    # No diarisation has run on this fixture row.
    assert rows[0]["Diarised Transcript"] == ""
    # Default evaluation transcript_source is production and this row has a CSV transcript.
    assert rows[0]["Evaluated Transcript Source"] == "Production"


def test_export_omits_rationale_column_when_capture_rationale_false(
    authenticated_client, db_session, org_id, seed_org
):
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)

    plain_metric = _make_metric(
        db_session,
        org_id,
        name="Quality",
        capture_rationale=False,
    )

    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[plain_metric],
        metric_scores={
            str(plain_metric.id): {
                "value": 0.85,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    headers, rows = _parse_csv(response.content)

    assert "Quality" in headers
    assert "Quality - LLM Rationale" not in headers
    assert rows[0]["Quality"] == "0.85"


def test_export_handles_missing_rationale_value_gracefully(
    authenticated_client, db_session, org_id, seed_org
):
    """If the worker stored the value but no rationale (e.g. LLM returned
    nothing for the companion key), the rationale cell should be empty,
    NOT crash the export."""
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)

    metric = _make_metric(
        db_session,
        org_id,
        name="Resolution",
        capture_rationale=True,
        custom_data_type="enum",
        custom_config={"options": ["Resolved", "Unresolved"]},
    )

    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": "Resolved",
                "type": "enum",
                "metric_name": "Resolution",
                "options": ["Resolved", "Unresolved"],
                # ``rationale`` intentionally omitted
            }
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    headers, rows = _parse_csv(response.content)

    assert "Resolution - LLM Rationale" in headers
    assert rows[0]["Resolution"] == "Resolved"
    assert rows[0]["Resolution - LLM Rationale"] == ""


def test_export_pairs_each_metrics_value_and_rationale_in_order(
    authenticated_client, db_session, org_id, seed_org
):
    """Mixed columns: a rationale-capturing metric AND a plain metric in the
    same export. The plain metric must NOT get a phantom rationale column,
    and the rationale column must sit immediately after its own value
    column (not somewhere else in the header row)."""
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)

    a = _make_metric(
        db_session,
        org_id,
        name="Pitch Type",
        capture_rationale=True,
        custom_data_type="enum",
        custom_config={"options": ["A", "B"]},
    )
    b = _make_metric(
        db_session,
        org_id,
        name="Connect Plus",
        capture_rationale=False,
    )

    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[a, b],
        metric_scores={
            str(a.id): {
                "value": "A",
                "type": "enum",
                "metric_name": "Pitch Type",
                "options": ["A", "B"],
                "rationale": "Reason A",
            },
            str(b.id): {
                "value": True,
                "type": "boolean",
                "metric_name": "Connect Plus",
            },
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    headers, rows = _parse_csv(response.content)

    pitch_idx = headers.index("Pitch Type")
    rationale_idx = headers.index("Pitch Type - LLM Rationale")
    connect_idx = headers.index("Connect Plus")
    assert rationale_idx == pitch_idx + 1
    # Plain metric must not get a rationale column.
    assert "Connect Plus - LLM Rationale" not in headers
    # ``Connect Plus`` is selected after the rationale-capturing metric so
    # it must appear AFTER the rationale column in the header order.
    assert connect_idx > rationale_idx
    assert rows[0]["Pitch Type"] == "A"
    assert rows[0]["Pitch Type - LLM Rationale"] == "Reason A"
    assert rows[0]["Connect Plus"] == "True"


def test_export_surfaces_both_transcripts_and_diarised_source(
    authenticated_client, db_session, org_id, seed_org
):
    """When the evaluation ran against the diarised transcript, the export
    must reflect that in the new ``Evaluated Transcript Source`` column and
    the live ``Diarised Transcript`` column must carry the worker output —
    independent of the frozen ``raw_columns`` snapshot."""
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    # Simulate the diarisation worker having run on this row.
    source_row.diarised_transcript = "worker output text"
    db_session.commit()

    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )

    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": 0.9,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )
    # Flip this evaluation's transcript_source to 'diarised' to mimic the
    # user picking the diarised transcript in the Run Evaluation modal.
    evaluation.transcript_source = "diarised"
    db_session.commit()

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    headers, rows = _parse_csv(response.content)

    assert "Production Transcript" in headers
    assert "Diarised Transcript" in headers
    assert "Evaluated Transcript Source" in headers
    assert rows[0]["Production Transcript"] == "hello world"
    assert rows[0]["Diarised Transcript"] == "worker output text"
    assert rows[0]["Evaluated Transcript Source"] == "Diarised"


def test_export_omits_diarised_source_when_diarised_transcript_missing(
    authenticated_client, db_session, org_id, seed_org
):
    """A diarised evaluation run must not label rows whose diarised transcript
    is still empty — the export should leave the source cell blank."""
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)

    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )

    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": 0.9,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )
    evaluation.transcript_source = "diarised"
    db_session.commit()

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    _headers, rows = _parse_csv(response.content)

    assert rows[0]["Diarised Transcript"] == ""
    assert rows[0]["Evaluated Transcript Source"] == ""


def test_export_diarised_source_is_per_row(
    authenticated_client, db_session, org_id, seed_org
):
    call_import = _make_call_import(db_session, org_id)
    row_without = _make_call_import_row(db_session, call_import, row_index=0)
    row_with = _make_call_import_row(db_session, call_import, row_index=1)
    row_with.diarised_transcript = "agent: hello\nuser: hi"
    db_session.commit()

    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        workspace_id=call_import.workspace_id,
        name="Mixed diarisation",
        selected_metric_ids=[str(metric.id)],
        transcript_source="diarised",
        status="completed",
        total_rows=2,
        completed_rows=2,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.commit()

    for source_row in (row_without, row_with):
        db_session.add(
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=evaluation.id,
                call_import_row_id=source_row.id,
                status="completed",
                metric_scores={
                    str(metric.id): {
                        "value": 0.9,
                        "type": "rating",
                        "metric_name": "Quality",
                    }
                },
            )
        )
    db_session.commit()

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    _headers, rows = _parse_csv(response.content)

    assert len(rows) == 2
    assert rows[0]["Evaluated Transcript Source"] == ""
    assert rows[1]["Evaluated Transcript Source"] == "Diarised"


def test_export_flattens_multi_line_diarised_transcript(
    authenticated_client, db_session, org_id, seed_org
):
    """Diarised transcripts are stored as ``<speaker>: <text>`` lines joined
    by ``\\n`` so the in-app TranscriptView can render chat bubbles. When
    exporting to CSV those newlines explode the spreadsheet cell vertically
    — every turn becomes its own line in Excel. The export endpoint must
    collapse them to a single space-separated line so the cell stays
    readable in Excel / Google Sheets without disturbing the DB shape."""
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    source_row.diarised_transcript = (
        "agent: hi there\nuser: hello\nagent: how can I help"
    )
    # Production transcript with a stray newline — both transcript columns
    # are flattened so the spreadsheet stays consistent regardless of
    # which source the operator picks.
    source_row.transcript = "line one\nline two"
    db_session.commit()

    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": 1.0,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    _, rows = _parse_csv(response.content)

    assert (
        rows[0]["Diarised Transcript"]
        == "agent: hi there user: hello agent: how can I help"
    )
    assert "\n" not in rows[0]["Diarised Transcript"]
    assert rows[0]["Production Transcript"] == "line one line two"
    assert "\n" not in rows[0]["Production Transcript"]


def test_export_supports_xlsx_format(
    authenticated_client, db_session, org_id, seed_org
):
    """Scores xlsx omits transcript bodies. Transcript CSV still flattens them."""
    import io as io_module

    from openpyxl import load_workbook

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    # Use Devanagari text + multi-line diarisation to exercise both the
    # unicode handling and the cell-flattening in the xlsx writer.
    source_row.diarised_transcript = "agent: नमस्ते\nuser: हेलो"
    db_session.commit()

    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": 0.75,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )

    transcript_csv = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    _csv_headers, csv_rows = _parse_csv(transcript_csv.content)
    assert csv_rows[0]["Diarised Transcript"] == "agent: नमस्ते user: हेलो"

    response = _render_export(
        db_session, call_import, evaluation, format="xlsx"
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    disposition = response.headers.get("content-disposition", "")
    assert ".xlsx" in disposition

    workbook = load_workbook(io_module.BytesIO(response.content), read_only=True)
    worksheet = workbook.active
    rows_iter = worksheet.iter_rows(values_only=True)
    header_row = list(next(rows_iter))
    assert "Production Transcript" in header_row
    assert "Diarised Transcript" in header_row
    assert "Quality" in header_row

    data_rows = [list(r) for r in rows_iter]
    assert len(data_rows) == 1
    assert data_rows[0][header_row.index("Diarised Transcript")] == "agent: नमस्ते user: हेलो"
    assert data_rows[0][header_row.index("Quality")] == "0.75"


def test_export_defaults_to_csv_when_format_omitted(
    authenticated_client, db_session, org_id, seed_org
):
    """Backwards-compat: callers that don't pass ``format`` still get the
    same CSV response they used to (UTF-8 BOM, ``text/csv`` content-type)."""
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": 0.5,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers.get("content-disposition", "")
    assert ".csv" in disposition


def test_export_includes_conversation_id_for_audio_upload(
    authenticated_client, db_session, org_id, seed_org
):
    """Manual audio uploads have no schema/column_mapping, but each row's
    filename-derived conversation_id must still appear in CSV/XLSX exports."""
    import io as io_module

    from openpyxl import load_workbook

    call_import = _make_audio_call_import(db_session, org_id)
    source_row = _make_audio_call_import_row(
        db_session, call_import, conversation_id="sales_call"
    )

    metric = _make_metric(
        db_session, org_id, name="Quality", capture_rationale=False
    )
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": 0.9,
                "type": "rating",
                "metric_name": "Quality",
            }
        },
    )

    csv_response = _render_export(
        db_session, call_import, evaluation, include_transcripts=True
    )
    assert csv_response.status_code == 200, csv_response.text
    headers, rows = _parse_csv(csv_response.content)

    assert headers[0] == "conversation_id"
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "sales_call"
    assert rows[0]["Quality"] == "0.9"

    xlsx_response = _render_export(
        db_session, call_import, evaluation, format="xlsx"
    )
    assert xlsx_response.status_code == 200, xlsx_response.text

    workbook = load_workbook(io_module.BytesIO(xlsx_response.content), read_only=True)
    worksheet = workbook.active
    rows_iter = worksheet.iter_rows(values_only=True)
    header_row = list(next(rows_iter))
    data_rows = [list(r) for r in rows_iter]

    assert header_row[0] == "conversation_id"
    assert len(data_rows) == 1
    assert data_rows[0][header_row.index("conversation_id")] == "sales_call"
    assert data_rows[0][header_row.index("Quality")] == "0.9"


def test_default_projector_omits_transcript_and_rationale(
    db_session, org_id, seed_org
):
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(
        db_session, org_id, name="Pitch Type", capture_rationale=True
    )
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={
            str(metric.id): {
                "value": "WITH data",
                "rationale": "because the pitch named the product",
            }
        },
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=False
    )
    headers, rows = _parse_csv(response.content)
    assert "Transcript" not in headers
    assert "Production Transcript" not in headers
    assert "Diarised Transcript" not in headers
    assert "Pitch Type - LLM Rationale" not in headers
    assert "Evaluated Transcript Source" in headers
    assert rows[0]["Pitch Type"] == "WITH data"
    assert "because the pitch named the product" not in response.text


def test_default_export_query_does_not_select_transcript_columns(db_session):
    from sqlalchemy.dialects import postgresql

    from app.services.call_imports.evaluation_export import export_page_query

    def _sql(*, include_transcripts: bool) -> str:
        query = export_page_query(
            db_session, uuid4(), include_transcripts=include_transcripts
        )
        return " ".join(
            str(query.statement.compile(dialect=postgresql.dialect())).lower().split()
        )

    default_sql = _sql(include_transcripts=False)
    assert "call_import_rows.transcript" not in default_sql
    assert "diarised_transcript" not in default_sql

    transcript_sql = _sql(include_transcripts=True)
    assert "call_import_rows.transcript" in transcript_sql
    assert "call_import_rows.diarised_transcript" in transcript_sql


def test_export_start_returns_job_and_status_returns_one_link_per_part(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    import os
    from uuid import UUID

    from app.services.call_imports.evaluation_export import execute_evaluation_export
    from app.services.storage.blob_storage_service import blob_storage_service
    import app.workers.tasks.call_import_bulk_ops as bulk

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={str(metric.id): {"value": 1, "metric_name": "Quality"}},
    )

    uploads = []

    def _upload(path, key, content_type=None):
        assert isinstance(path, str)
        assert os.path.isfile(path)
        assert not isinstance(path, (bytes, bytearray))
        uploads.append((path, key, content_type))

    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.call_imports.evaluation_export._export_object_key",
        lambda job, filename: f"tests/{job.id}/{filename}",
    )
    monkeypatch.setattr(blob_storage_service, "upload_file_by_key_from_path", _upload)
    monkeypatch.setattr(
        blob_storage_service,
        "generate_presigned_url_by_key",
        lambda key, expiration=3600, response_content_disposition=None: (
            f"https://files.example/{key}"
        ),
    )

    def _delay(job_id):
        execute_evaluation_export(db_session, UUID(job_id))
        return type("Task", (), {"id": "inline-export"})()

    monkeypatch.setattr(bulk.export_call_import_evaluation_task, "delay", _delay)

    started = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export",
        json={"format": "csv"},
    )
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["status"] == "completed"
    assert body["include_transcripts"] is True
    assert len(uploads) == 1
    assert uploads[0][0].endswith(".csv.gz")
    assert uploads[0][2] == "application/gzip"

    status = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}"
        f"/export-jobs/{body['id']}"
    )
    assert status.status_code == 200
    assert status.headers["content-type"].startswith("application/json")
    payload = status.json()
    assert len(payload["parts"]) == 1
    assert payload["parts"][0]["download_url"].startswith("https://files.example/")
    assert payload["parts"][0]["row_count"] == 1
    assert "hello world" not in status.text


def test_second_export_reuses_the_pending_job(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)

    url = f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export"
    first = authenticated_client.post(url, json={"format": "csv"})
    second = authenticated_client.post(url, json={"format": "csv"})
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "pending"


def test_xlsx_past_sheet_cap_is_rejected(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.count_evaluation_rows_for_run",
        lambda *_args, **_kwargs: 1_048_577,
    )
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export",
        json={"format": "xlsx"},
    )
    assert response.status_code == 400
    assert "Excel" in response.json()["detail"]


def test_xlsx_export_includes_transcripts(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export",
        json={"format": "xlsx"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["include_transcripts"] is True
    assert response.json()["format"] == "xlsx"


def test_quarter_million_rows_upload_three_gzip_parts(
    db_session, org_id, seed_org, monkeypatch
):
    import os
    from uuid import UUID

    from app.models.database import CallImportEvaluationExport
    from app.services.call_imports import evaluation_export as export_mod
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    job = CallImportEvaluationExport(
        evaluation_id=evaluation.id,
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        workspace_id=call_import.workspace_id,
        format="csv",
        include_transcripts=False,
        status="pending",
        parts=[],
    )
    db_session.add(job)
    db_session.commit()

    def _pairs(*_args, **_kwargs):
        for _ in range(250_000):
            yield object(), object()

    uploads = []

    def _upload(path, key, content_type=None):
        assert isinstance(path, str)
        assert os.path.isfile(path)
        assert path.endswith(".csv.gz")
        uploads.append(
            {
                "path": path,
                "key": key,
                "content_type": content_type,
                "byte_size": os.path.getsize(path),
            }
        )

    monkeypatch.setattr(export_mod, "iter_export_pairs", _pairs)
    monkeypatch.setattr(export_mod, "project_export_row", lambda *_a, **_k: {"CallID": "c"})
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        export_mod,
        "_export_object_key",
        lambda job, filename: f"tests/{job.id}/{filename}",
    )
    monkeypatch.setattr(blob_storage_service, "upload_file_by_key_from_path", _upload)

    result = export_mod.execute_evaluation_export(db_session, job.id)
    assert result["status"] == "completed"
    assert result["parts"] == 1
    assert len(uploads) == 1
    db_session.refresh(job)
    assert [part["row_count"] for part in job.parts] == [250_000]
    assert job.parts[0]["filename"].endswith(".csv.gz")
    assert "-part-" not in job.parts[0]["filename"]


def _pending_export_job(db_session, call_import, evaluation):
    from app.models.database import CallImportEvaluationExport

    job = CallImportEvaluationExport(
        evaluation_id=evaluation.id,
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        workspace_id=call_import.workspace_id,
        format="csv",
        include_transcripts=False,
        status="pending",
        parts=[],
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_fresh_running_export_is_not_scanned_again(
    db_session, org_id, seed_org, monkeypatch
):
    from datetime import datetime, timezone

    from app.services.call_imports import evaluation_export as export_mod
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    job = _pending_export_job(db_session, call_import, evaluation)
    job.status = "running"
    job.heartbeat_at = datetime.now(timezone.utc)
    job.claim_token = "live-worker"
    db_session.commit()

    uploads = []
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        blob_storage_service,
        "upload_file_by_key_from_path",
        lambda *args, **kwargs: uploads.append(args),
    )

    result = export_mod.execute_evaluation_export(db_session, job.id)
    assert result["status"] == "running"
    assert result["retry_after_seconds"] >= 5
    assert uploads == []
    db_session.refresh(job)
    assert job.claim_token == "live-worker"


def test_stale_running_export_is_scanned_again(
    db_session, org_id, seed_org, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    from app.services.call_imports import evaluation_export as export_mod
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={str(metric.id): {"value": 1}},
    )
    job = _pending_export_job(db_session, call_import, evaluation)
    job.status = "running"
    job.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    job.claim_token = "dead-worker"
    db_session.commit()

    uploads = []
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        export_mod,
        "_export_object_key",
        lambda owned, filename: f"tests/{owned.id}/{filename}",
    )
    monkeypatch.setattr(
        blob_storage_service,
        "upload_file_by_key_from_path",
        lambda path, key, content_type=None: uploads.append(path),
    )

    result = export_mod.execute_evaluation_export(db_session, job.id)
    assert result["status"] == "completed", result
    assert len(uploads) == 1
    assert uploads[0].endswith(".csv.gz")
    db_session.refresh(job)
    assert job.claim_token != "dead-worker"
    assert job.parts[0]["row_count"] == 1


def test_storage_disabled_fails_the_job(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: False)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export",
        json={"format": "csv"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert "storage" in body["error_message"].lower()


def test_live_running_export_is_not_queued_again(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    from datetime import datetime, timezone

    from app.services.storage.blob_storage_service import blob_storage_service
    import app.workers.tasks.call_import_bulk_ops as bulk

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    job = _pending_export_job(db_session, call_import, evaluation)
    job.status = "running"
    job.include_transcripts = True
    job.heartbeat_at = datetime.now(timezone.utc)
    job.claim_token = "live-worker"
    db_session.commit()

    queued = []
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        bulk.export_call_import_evaluation_task,
        "delay",
        lambda job_id: queued.append(job_id),
    )
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export",
        json={"format": "csv"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "running"
    assert body["format"] == "csv"
    assert queued == []


def test_different_export_while_one_is_running_is_rejected(
    authenticated_client, db_session, org_id, seed_org
):
    from datetime import datetime, timezone

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    job = _pending_export_job(db_session, call_import, evaluation)
    job.status = "running"
    job.heartbeat_at = datetime.now(timezone.utc)
    db_session.commit()

    url = f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export"
    excel = authenticated_client.post(url, json={"format": "xlsx"})
    transcripts = authenticated_client.post(
        url, json={"format": "csv", "include_transcripts": True}
    )
    assert excel.status_code == 409, excel.text
    assert transcripts.status_code == 409, transcripts.text
    db_session.refresh(job)
    assert job.status == "running"
    assert job.format == "csv"
    assert job.include_transcripts is False


def test_scores_export_omits_schema_transcript_parameter(
    db_session, org_id, seed_org
):
    from app.models.database import CallImportSchema, CallImportSchemaParameter

    call_import = _make_call_import(db_session, org_id)
    schema = CallImportSchema(
        organization_id=call_import.organization_id,
        workspace_id=call_import.workspace_id,
        name="Voice QA",
    )
    db_session.add(schema)
    db_session.commit()
    db_session.add_all(
        [
            CallImportSchemaParameter(
                schema_id=schema.id,
                name="Call Text",
                type="transcript",
                ordering=0,
            ),
            CallImportSchemaParameter(
                schema_id=schema.id,
                name="Agent",
                type="text",
                ordering=1,
            ),
        ]
    )
    call_import.schema_id = schema.id
    db_session.commit()
    source_row = _make_call_import_row(
        db_session,
        call_import,
        raw_columns={"Call Text": "secret transcript", "Agent": "Ada"},
    )
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={str(metric.id): {"value": 1}},
    )

    response = _render_export(
        db_session, call_import, evaluation, include_transcripts=False
    )
    headers, rows = _parse_csv(response.content)
    assert "Call Text" not in headers
    assert "Agent" in headers
    assert rows[0]["Agent"] == "Ada"
    assert "secret transcript" not in response.text


def test_failed_enqueue_marks_the_job_failed(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    from app.services.storage.blob_storage_service import blob_storage_service
    import app.workers.tasks.call_import_bulk_ops as bulk

    call_import = _make_call_import(db_session, org_id)
    source_row = _make_call_import_row(db_session, call_import)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=source_row,
        metrics=[metric],
        metric_scores={},
    )
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)

    def _delay(_job_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr(bulk.export_call_import_evaluation_task, "delay", _delay)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/export",
        json={"format": "csv"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert "queue" in body["error_message"].lower()


def test_export_commits_each_page(
    db_session, org_id, seed_org, monkeypatch
):
    from app.models.database import CallImportEvaluationRow
    from app.services.call_imports import evaluation_export as export_mod
    from app.services.storage.blob_storage_service import blob_storage_service

    call_import = _make_call_import(db_session, org_id)
    first = _make_call_import_row(db_session, call_import, row_index=0)
    second = _make_call_import_row(db_session, call_import, row_index=1)
    metric = _make_metric(db_session, org_id, name="Quality")
    evaluation = _make_evaluation_with_row(
        db_session,
        call_import=call_import,
        source_row=first,
        metrics=[metric],
        metric_scores={},
    )
    db_session.add(
        CallImportEvaluationRow(
            evaluation_id=evaluation.id,
            call_import_row_id=second.id,
            status="completed",
            metric_scores={},
        )
    )
    db_session.commit()
    job = _pending_export_job(db_session, call_import, evaluation)

    commits = {"n": 0}
    original_commit = db_session.commit

    def _commit():
        commits["n"] += 1
        return original_commit()

    monkeypatch.setattr(export_mod, "EXPORT_PAGE_SIZE", 1)
    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(blob_storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        export_mod,
        "_export_object_key",
        lambda owned, filename: f"tests/{owned.id}/{filename}",
    )
    monkeypatch.setattr(
        blob_storage_service,
        "upload_file_by_key_from_path",
        lambda *args, **kwargs: None,
    )

    result = export_mod.execute_evaluation_export(db_session, job.id)
    assert result["status"] == "completed", result
    assert result["parts"] == 1
    # Claim, layout, one commit per page, and the final write. One commit
    # for the whole file would stay under this.
    assert commits["n"] >= 4
