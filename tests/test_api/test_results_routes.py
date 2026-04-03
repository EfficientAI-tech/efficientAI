"""API tests for results routes."""

import pytest


def test_get_result_without_result_returns_placeholder(authenticated_client, make_evaluation):
    evaluation = make_evaluation()

    response = authenticated_client.get(f"/api/v1/results/{evaluation.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_id"] == str(evaluation.id)
    assert body["metrics"] == {}
    assert body["transcript"] is None


def test_get_metrics_returns_404_when_result_missing(authenticated_client, make_evaluation):
    evaluation = make_evaluation()

    response = authenticated_client.get(f"/api/v1/results/{evaluation.id}/metrics")

    assert response.status_code == 404
    assert response.json()["detail"] == "Results not found for this evaluation"


def test_get_metrics_returns_data(authenticated_client, make_evaluation, make_evaluation_result):
    evaluation = make_evaluation()
    make_evaluation_result(evaluation, metrics={"wer": 0.2, "latency_ms": 450}, processing_time=0.45)

    response = authenticated_client.get(f"/api/v1/results/{evaluation.id}/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_id"] == str(evaluation.id)
    assert body["metrics"]["wer"] == 0.2
    assert body["processing_time"] == 0.45


def test_compare_evaluations_returns_aggregates(
    authenticated_client, make_evaluation, make_evaluation_result
):
    eval_one = make_evaluation()
    eval_two = make_evaluation()
    make_evaluation_result(eval_one, metrics={"wer": 0.2, "latency_ms": 300})
    make_evaluation_result(eval_two, metrics={"wer": 0.4, "latency_ms": 500})

    payload = {"evaluation_ids": [str(eval_one.id), str(eval_two.id)]}
    response = authenticated_client.post("/api/v1/results/compare", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert len(body["evaluations"]) == 2
    assert body["comparison_metrics"]["wer_min"] == 0.2
    assert body["comparison_metrics"]["wer_max"] == 0.4
    assert body["comparison_metrics"]["wer_avg"] == pytest.approx(0.3)
