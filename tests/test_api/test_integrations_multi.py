"""API tests for the multi-credential voice ``Integration`` routes.

Validates the new behavior added when we lifted the API-side guard that
rejected duplicate ``(org, platform, is_active=True)`` rows. We can now
hold multiple credentials per platform, with at most one ``is_default``
row enforced by application code (and a partial unique index on
Postgres).
"""

from uuid import UUID

from sqlalchemy import func

from app.models.database import Integration


def _create_integration(client, *, platform="retell", api_key="key", name=None, is_default=None):
    payload = {"platform": platform, "api_key": api_key}
    if name is not None:
        payload["name"] = name
    if is_default is not None:
        payload["is_default"] = is_default
    response = client.post("/api/v1/integrations", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_first_integration_is_auto_default(authenticated_client):
    body = _create_integration(authenticated_client, name="Primary Retell")
    assert body["is_default"] is True


def test_multiple_active_integrations_allowed(authenticated_client):
    first = _create_integration(authenticated_client, name="Primary")
    second = _create_integration(authenticated_client, name="Backup", api_key="key-2")

    listing = authenticated_client.get("/api/v1/integrations").json()
    assert len(listing) == 2
    by_id = {row["id"]: row for row in listing}
    assert by_id[first["id"]]["is_default"] is True
    assert by_id[second["id"]]["is_default"] is False


def test_set_default_swaps_flag(authenticated_client, db_session, org_id):
    first = _create_integration(authenticated_client, name="Primary")
    second = _create_integration(authenticated_client, name="Backup", api_key="key-2")

    response = authenticated_client.post(f"/api/v1/integrations/{second['id']}/set-default")
    assert response.status_code == 200
    assert response.json()["is_default"] is True

    defaults = (
        db_session.query(Integration)
        .filter(
            Integration.organization_id == org_id,
            func.lower(Integration.platform) == "retell",
            Integration.is_default.is_(True),
        )
        .all()
    )
    assert len(defaults) == 1
    assert str(defaults[0].id) == second["id"]

    # Coerce JSON id string to UUID; the UUID bind processor on SQLite
    # expects a UUID instance and would otherwise fail with
    # ``'str' object has no attribute 'hex'``.
    refreshed_first = db_session.get(Integration, UUID(first["id"]))
    assert refreshed_first.is_default is False


def test_delete_default_promotes_active_replacement(authenticated_client):
    default_row = _create_integration(authenticated_client, name="Primary")
    backup = _create_integration(authenticated_client, name="Backup", api_key="key-2")

    response = authenticated_client.delete(f"/api/v1/integrations/{default_row['id']}")
    assert response.status_code in (200, 204)

    listing = authenticated_client.get("/api/v1/integrations").json()
    assert len(listing) == 1
    assert listing[0]["id"] == backup["id"]
    assert listing[0]["is_default"] is True
