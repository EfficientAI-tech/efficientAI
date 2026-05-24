"""API tests for the multi-credential AIProvider routes.

Covers the new behavior introduced when we lifted the
``unique(org, provider)`` constraint on ``aiproviders``:

* multiple rows per ``(org, provider)`` are allowed,
* the first row created for a provider is auto-promoted to default,
* ``POST /aiproviders/{id}/set-default`` flips the default flag and
  clears it on every other row for the same ``(org, provider)``,
* deleting the default row promotes the next active row.
"""

from uuid import UUID

from sqlalchemy import func

from app.models.database import AIProvider


def _create_provider(client, *, name, provider="openai", api_key="sk-1", is_default=None):
    payload = {"provider": provider, "api_key": api_key, "name": name}
    if is_default is not None:
        payload["is_default"] = is_default
    response = client.post("/api/v1/aiproviders", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_first_provider_is_auto_default(authenticated_client):
    body = _create_provider(authenticated_client, name="Primary OpenAI")
    assert body["name"] == "Primary OpenAI"
    assert body["is_default"] is True


def test_subsequent_provider_does_not_steal_default(authenticated_client):
    first = _create_provider(authenticated_client, name="Primary")
    second = _create_provider(authenticated_client, name="Backup", api_key="sk-2")

    assert first["is_default"] is True
    assert second["is_default"] is False

    listing = authenticated_client.get("/api/v1/aiproviders").json()
    assert len(listing) == 2
    # Default row is sorted first by the route.
    assert listing[0]["id"] == first["id"]
    assert listing[0]["is_default"] is True


def test_set_default_swaps_flag_atomically(authenticated_client, db_session, org_id):
    first = _create_provider(authenticated_client, name="Primary")
    second = _create_provider(authenticated_client, name="Backup", api_key="sk-2")

    response = authenticated_client.post(f"/api/v1/aiproviders/{second['id']}/set-default")
    assert response.status_code == 200
    assert response.json()["is_default"] is True

    # The DB should now show exactly one default for this (org, provider).
    defaults = (
        db_session.query(AIProvider)
        .filter(
            AIProvider.organization_id == org_id,
            func.lower(AIProvider.provider) == "openai",
            AIProvider.is_default.is_(True),
        )
        .all()
    )
    assert len(defaults) == 1
    assert str(defaults[0].id) == second["id"]
    # And the previously-default row should be cleared. Coerce the JSON id
    # string to UUID — SQLAlchemy's UUID(as_uuid=True) bind processor (used
    # here on SQLite as CHAR(32)) calls ``value.hex`` and only accepts UUID
    # instances.
    other = db_session.get(AIProvider, UUID(first["id"]))
    assert other.is_default is False


def test_explicit_is_default_on_create_promotes_new_row(authenticated_client):
    first = _create_provider(authenticated_client, name="Primary")
    new_default = _create_provider(
        authenticated_client, name="New Default", api_key="sk-3", is_default=True
    )

    assert new_default["is_default"] is True

    listing = {row["id"]: row for row in authenticated_client.get("/api/v1/aiproviders").json()}
    assert listing[first["id"]]["is_default"] is False
    assert listing[new_default["id"]]["is_default"] is True


def test_delete_default_promotes_replacement(authenticated_client):
    primary = _create_provider(authenticated_client, name="Primary")
    backup = _create_provider(authenticated_client, name="Backup", api_key="sk-2")

    response = authenticated_client.delete(f"/api/v1/aiproviders/{primary['id']}")
    assert response.status_code == 204

    listing = authenticated_client.get("/api/v1/aiproviders").json()
    assert len(listing) == 1
    assert listing[0]["id"] == backup["id"]
    assert listing[0]["is_default"] is True
