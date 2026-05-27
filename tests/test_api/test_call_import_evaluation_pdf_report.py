import io
import zipfile
from uuid import UUID, uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus, MetricType
from app.services.reporting.call_import_evaluation_pdf_report import (
    call_import_evaluation_pdf_report_service,
)


def _default_workspace_id(db_session, org_id) -> UUID:
    workspace = (
        db_session.query(Workspace)
        .filter(
            Workspace.organization_id == org_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    assert workspace is not None
    return workspace.id


def _seed_completed_evaluation(db_session, org_id):
    workspace_id = _default_workspace_id(db_session, org_id)
    metric = Metric(
        organization_id=org_id,
        workspace_id=workspace_id,
        name="Escalation Handling",
        description="Checks whether customer escalation was handled correctly.",
        metric_type=MetricType.BOOLEAN.value,
        supported_surfaces=["call_imports"],
        enabled_surfaces=["call_imports"],
        capture_rationale=True,
        enabled=True,
    )
    call_import = CallImport(
        organization_id=org_id,
        workspace_id=workspace_id,
        provider=None,
        original_filename="manual-audio",
        source_format="audio",
        dataset="Manual recordings",
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add_all([metric, call_import])
    db_session.flush()

    source_row = CallImportRow(
        call_import_id=call_import.id,
        organization_id=org_id,
        row_index=1,
        conversation_id="call-001",
        transcript="Agent: Hello. Customer: I need this escalated.",
        diarised_transcript="agent: Hello.\nuser: I need this escalated.",
        raw_columns={"conversation_id": "call-001"},
        transcript_source="csv",
        status=CallImportRowStatus.COMPLETED,
    )
    evaluation = CallImportEvaluation(
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace_id,
        name="Weekly QA",
        selected_metric_ids=[str(metric.id)],
        selected_metric_groups={},
        status="completed",
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        transcript_source="diarised",
    )
    db_session.add_all([source_row, evaluation])
    db_session.flush()

    eval_row = CallImportEvaluationRow(
        evaluation_id=evaluation.id,
        call_import_row_id=source_row.id,
        status="completed",
        metric_scores={
            str(metric.id): {
                "value": True,
                "type": "boolean",
                "rationale": "Customer escalation was not handled.",
            }
        },
    )
    db_session.add(eval_row)
    db_session.commit()
    return call_import, evaluation


def test_pdf_report_rejects_blank_vendor_name(authenticated_client):
    response = authenticated_client.post(
        f"/api/v1/call-imports/{uuid4()}/evaluations/{uuid4()}/pdf-report",
        json={"vendor_name": "   "},
    )

    assert response.status_code == 422


def test_pdf_report_generates_external_and_internal_pdfs(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    monkeypatch.setattr(
        call_import_evaluation_pdf_report_service,
        "_render_weasyprint",
        lambda _html: None,
    )
    call_import, evaluation = _seed_completed_evaluation(db_session, org_id)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/pdf-report",
        json={"vendor_name": "Acme Vendor"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    assert "acme-vendor-quality-metric-audit" in response.headers[
        "content-disposition"
    ]

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == [
        "external-quality-metric-audit.pdf",
        "internal-quality-metric-audit.pdf",
    ]

    external_pdf = archive.read("external-quality-metric-audit.pdf")
    internal_pdf = archive.read("internal-quality-metric-audit.pdf")
    assert external_pdf.startswith(b"%PDF-1.4")
    assert internal_pdf.startswith(b"%PDF-1.4")
    assert b"Acme Vendor" in external_pdf
    assert b"Escalation Handling" in external_pdf
    assert b"Customer escalation was not handled" in external_pdf
    assert b"Methodology" in external_pdf
    assert b"Internal Diagnostics" not in external_pdf
    assert b"Evaluation Row ID" not in external_pdf
    assert b"Internal Diagnostics" in internal_pdf
    assert b"Evaluation Row ID" in internal_pdf
