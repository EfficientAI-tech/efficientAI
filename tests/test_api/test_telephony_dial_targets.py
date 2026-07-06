"""API tests for org-level telephony dial targets."""

from uuid import uuid4

from app.models.database import Organization, TelephonyDialTarget


def test_create_and_list_dial_targets(client, org_id, seed_org):
    response = client.post(
        "/api/v1/telephony/dial-targets",
        json={"phone_number": "+919111111111", "label": "QA line"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["phone_number"] == "+919111111111"
    assert body["label"] == "QA line"

    list_response = client.get("/api/v1/telephony/dial-targets")
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert items[0]["phone_number"] == "+919111111111"


def test_create_duplicate_dial_target_returns_409(client, org_id, seed_org):
    client.post(
        "/api/v1/telephony/dial-targets",
        json={"phone_number": "+919222222222"},
    )
    duplicate = client.post(
        "/api/v1/telephony/dial-targets",
        json={"phone_number": "+919222222222", "label": "Other"},
    )
    assert duplicate.status_code == 409


def test_delete_dial_target(client, db_session, org_id, seed_org):
    row = TelephonyDialTarget(
        id=uuid4(),
        organization_id=org_id,
        phone_number="+919333333333",
        label="Remove me",
    )
    db_session.add(row)
    db_session.commit()

    response = client.delete(f"/api/v1/telephony/dial-targets/{row.id}")
    assert response.status_code == 204

    db_session.expire_all()
    assert db_session.query(TelephonyDialTarget).filter(TelephonyDialTarget.id == row.id).first() is None


def test_dial_targets_are_org_scoped(client, db_session, org_id, seed_org):
    other_org_id = uuid4()
    db_session.add(Organization(id=other_org_id, name="Other Org"))
    db_session.add(
        TelephonyDialTarget(
            id=uuid4(),
            organization_id=other_org_id,
            phone_number="+919444444444",
            label="Other org",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/telephony/dial-targets")
    assert response.status_code == 200
    assert response.json() == []
