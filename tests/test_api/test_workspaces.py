"""End-to-end tests for the workspace CRUD routes and workspace scoping
on metrics + call imports.

The TestClient wires the test ``org_id`` to the fixture-seeded Default
workspace via ``get_workspace_id`` (see tests/conftest.py). Tests that
exercise a *non-default* workspace switch the override on the fly and
revert it in a finally so subsequent tests start from a clean slate.
"""

from __future__ import annotations

from uuid import uuid4

from app.dependencies import get_workspace_id
from app.models.database import (
    CallImport,
    CallImportStatus,
    Metric,
    Workspace,
)
from app.services.workspace_rbac import seed_system_workspace_roles


def test_create_and_list_workspaces(authenticated_client, db_session, org_id):
    seed_system_workspace_roles(db_session, organization_id=org_id)
    response = authenticated_client.post(
        "/api/v1/workspaces", json={"name": "Project Phoenix"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Project Phoenix"
    assert body["slug"] == "project_phoenix"
    assert body["is_default"] is False
    assert body["organization_id"] == str(org_id)
    assert body.get("capabilities")

    listing = authenticated_client.get("/api/v1/workspaces").json()
    names = [w["name"] for w in listing]
    assert "Project Phoenix" in names


def test_create_workspace_rejects_default_slug(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/workspaces", json={"name": "Default", "slug": "default"}
    )
    assert response.status_code == 409
    assert "default" in response.json()["detail"].lower()


def test_delete_default_workspace_is_blocked(authenticated_client, db_session, org_id):
    default = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    response = authenticated_client.delete(f"/api/v1/workspaces/{default.id}")
    assert response.status_code == 400
    assert "default" in response.json()["detail"].lower()


def test_metrics_scope_to_active_workspace(
    authenticated_client, db_session, org_id, make_metric, default_workspace
):
    """Metrics in workspace A must not show up when the active workspace is B."""

    # Seed: one metric in the Default workspace.
    make_metric(name="A-only metric")

    # Create a sibling workspace + metric directly via the ORM so we
    # don't need to flip the dep override mid-test.
    workspace_b = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Workspace B",
        slug="workspace_b",
        is_default=False,
    )
    db_session.add(workspace_b)
    db_session.commit()
    db_session.add(
        Metric(
            id=uuid4(),
            organization_id=org_id,
            workspace_id=workspace_b.id,
            name="B-only metric",
            metric_type="rating",
            trigger="always",
            enabled=True,
        )
    )
    db_session.commit()

    # Active workspace = Default => only A is visible.
    listing = authenticated_client.get("/api/v1/metrics").json()
    names = {m["name"] for m in listing}
    assert "A-only metric" in names
    assert "B-only metric" not in names

    # Flip the workspace override; only B is visible.
    app = authenticated_client.app
    previous = app.dependency_overrides[get_workspace_id]
    app.dependency_overrides[get_workspace_id] = lambda: workspace_b.id
    try:
        listing = authenticated_client.get("/api/v1/metrics").json()
    finally:
        app.dependency_overrides[get_workspace_id] = previous

    names = {m["name"] for m in listing}
    assert "B-only metric" in names
    assert "A-only metric" not in names


def test_call_imports_scope_to_active_workspace(
    authenticated_client, db_session, org_id, default_workspace
):
    workspace_b = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Workspace B",
        slug="workspace_b",
        is_default=False,
    )
    db_session.add(workspace_b)
    # Commit the workspace before adding child rows that reference it.
    # SQLAlchemy's dependency sort can emit the CallImport insertmany
    # batch ahead of the Workspace insert in the same flush; Postgres
    # (CI) enforces the FK immediately and rejects it, whereas SQLite
    # (local) silently allows the orphan reference.
    db_session.commit()

    db_session.add(
        CallImport(
            id=uuid4(),
            organization_id=org_id,
            workspace_id=default_workspace.id,
            provider="exotel",
            original_filename="default.csv",
            column_mapping={"external_call_id": "CallID"},
            extra_columns=[],
            custom_column_mapping={},
            total_rows=0,
            completed_rows=0,
            failed_rows=0,
            status=CallImportStatus.COMPLETED,
        )
    )
    db_session.add(
        CallImport(
            id=uuid4(),
            organization_id=org_id,
            workspace_id=workspace_b.id,
            provider="exotel",
            original_filename="b.csv",
            column_mapping={"external_call_id": "CallID"},
            extra_columns=[],
            custom_column_mapping={},
            total_rows=0,
            completed_rows=0,
            failed_rows=0,
            status=CallImportStatus.COMPLETED,
        )
    )
    db_session.commit()

    # Default workspace -> only default.csv is visible.
    body = authenticated_client.get("/api/v1/call-imports").json()
    files = {item["original_filename"] for item in body["items"]}
    assert files == {"default.csv"}

    app = authenticated_client.app
    previous = app.dependency_overrides[get_workspace_id]
    app.dependency_overrides[get_workspace_id] = lambda: workspace_b.id
    try:
        body = authenticated_client.get("/api/v1/call-imports").json()
    finally:
        app.dependency_overrides[get_workspace_id] = previous

    files = {item["original_filename"] for item in body["items"]}
    assert files == {"b.csv"}


def test_promote_discovered_child_enables_rationale_capture(
    authenticated_client, db_session, org_id, make_metric
):
    """Promoting a discovered label must default ``capture_rationale=true``
    so future rows that hit the new child keep producing rationales,
    matching the v1 product behavior.
    """

    parent = make_metric(
        name="Discovered Parent",
        metric_type="text",
        selection_mode="multi_label",
        allow_discovery=True,
    )

    response = authenticated_client.post(
        f"/api/v1/metrics/{parent.id}/children/from-discovered",
        json={
            "key": "customer_on_hold",
            "name": "customer on hold",
            "description": (
                "caller paused\n\nExamples:\n- \"Please hold a moment\"\n"
                "- \"Could you wait?\""
            ),
        },
    )
    assert response.status_code == 201, response.text

    # Refetch the parent with children inlined and assert the new child
    # is captured-rationale-enabled and carries the Examples block.
    detail = authenticated_client.get(f"/api/v1/metrics/{parent.id}").json()
    children = detail["children"]
    assert len(children) == 1
    child = children[0]
    assert child["capture_rationale"] is True
    assert "Examples:" in (child["description"] or "")
    assert "Please hold a moment" in (child["description"] or "")


def test_promote_honors_explicit_capture_rationale_false(
    authenticated_client, db_session, org_id, make_metric
):
    """A caller can still opt out of rationale capture by passing
    ``capture_rationale=false`` explicitly."""

    parent = make_metric(
        name="No Rationale Parent",
        metric_type="text",
        selection_mode="multi_label",
        allow_discovery=True,
    )
    response = authenticated_client.post(
        f"/api/v1/metrics/{parent.id}/children/from-discovered",
        json={
            "key": "no_rationale",
            "name": "no rationale",
            "capture_rationale": False,
        },
    )
    assert response.status_code == 201
    detail = authenticated_client.get(f"/api/v1/metrics/{parent.id}").json()
    assert detail["children"][0]["capture_rationale"] is False
