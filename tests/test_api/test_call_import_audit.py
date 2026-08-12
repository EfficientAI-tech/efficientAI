"""Audit fields (created_by / last_updated_by email) on call imports."""

from uuid import uuid4

from app.models.database import CallImport, Workspace
from app.models.enums import CallImportStatus


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


def test_update_call_import_metadata_stamps_actor_emails(
    authenticated_client, db_session, org_id, seed_org
):
    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        original_filename="batch.csv",
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
        dataset="before",
    )
    db_session.add(call_import)
    db_session.commit()

    response = authenticated_client.patch(
        f"/api/v1/call-imports/{call_import.id}",
        json={"dataset": "after"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset"] == "after"
    assert body["created_by_email"] is None
    assert body["last_updated_by_email"] == "owner@example.com"


def test_list_call_imports_includes_actor_emails(
    authenticated_client, db_session, org_id, seed_org
):
    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider=None,
        original_filename="listed.csv",
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.UPLOADED,
    )
    db_session.add(call_import)
    db_session.commit()

    listing = authenticated_client.get("/api/v1/call-imports")
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    match = [item for item in items if item["id"] == str(call_import.id)]
    assert len(match) == 1
    assert match[0]["created_by_email"] is None
    assert match[0]["last_updated_by_email"] is None
