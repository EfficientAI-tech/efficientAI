"""Free-text search on evaluation row list API."""

from app.models.database import CallImportRow
from tests.test_api.test_call_import_evaluation_rows_sorting import _ids, _seed_eval_with_rows


def test_evaluation_rows_search_by_conversation_id_substring(
    authenticated_client, db_session, org_id
):
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "batch-alpha-001", "status": "completed", "score_value": 1},
            {"conversation_id": "batch-alpha-002", "status": "completed", "score_value": 1},
            {"conversation_id": "other-999", "status": "completed", "score_value": 1},
        ],
    )
    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"q": "alpha-00"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert set(_ids(body["items"])) == {"batch-alpha-001", "batch-alpha-002"}


def test_evaluation_rows_search_by_transcript(
    authenticated_client, db_session, org_id
):
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "c-one", "status": "completed", "score_value": 1},
            {"conversation_id": "c-two", "status": "completed", "score_value": 1},
        ],
    )
    source_rows = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )
    source_rows[0].transcript = "customer mentioned REFUND-42 today"
    source_rows[1].transcript = "unrelated call"
    db_session.commit()

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"q": "REFUND-42"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["conversation_id"] == "c-one"


def test_evaluation_rows_search_percent_literal_not_wildcard(
    authenticated_client, db_session, org_id
):
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "pct-call", "status": "completed", "score_value": 1},
            {"conversation_id": "plain-call", "status": "completed", "score_value": 1},
        ],
    )
    row = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .first()
    )
    row.transcript = "discount is 50% off"
    db_session.commit()

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"q": "50%"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1

    response_all = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"q": "%"},
    )
    assert response_all.status_code == 200, response_all.text
    assert response_all.json()["total"] == 2
