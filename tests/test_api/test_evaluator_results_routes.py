"""API tests for evaluator results routes."""


def test_list_and_get_evaluator_results(authenticated_client, make_evaluator_result):
    result = make_evaluator_result(result_id="778899", status="completed")

    list_response = authenticated_client.get("/api/v1/evaluator-results")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 0  # default excludes playground (evaluator_id is null)

    playground_response = authenticated_client.get("/api/v1/evaluator-results?playground=true")
    assert playground_response.status_code == 200
    assert len(playground_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/evaluator-results/{result.result_id}")
    assert get_response.status_code == 200
    assert get_response.json()["result_id"] == "778899"


def test_get_evaluator_result_metrics(authenticated_client, make_evaluator_result, make_metric):
    metric = make_metric(name="Professionalism")
    result = make_evaluator_result(
        result_id="445566",
        metric_scores={str(metric.id): {"value": 85, "type": "rating"}},
    )

    response = authenticated_client.get(f"/api/v1/evaluator-results/{result.result_id}/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["result_id"] == "445566"
    assert "Professionalism" in body["metrics"]
    assert body["metrics"]["Professionalism"]["value"] == 85


def test_delete_evaluator_result(authenticated_client, make_evaluator_result):
    result = make_evaluator_result(result_id="334455")

    response = authenticated_client.delete(f"/api/v1/evaluator-results/{result.result_id}")

    assert response.status_code == 204
