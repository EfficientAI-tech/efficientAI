"""API tests for cron-jobs routes."""


def test_create_list_get_update_toggle_delete_cron_job(authenticated_client, make_evaluator):
    evaluator = make_evaluator()
    payload = {
        "name": "Daily Eval Job",
        "cron_expression": "0 9 * * *",
        "timezone": "UTC",
        "max_runs": 10,
        "evaluator_ids": [str(evaluator.id)],
    }
    create_response = authenticated_client.post("/api/v1/cron-jobs", json=payload)
    assert create_response.status_code == 201
    cron_job_id = create_response.json()["id"]

    list_response = authenticated_client.get("/api/v1/cron-jobs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/cron-jobs/{cron_job_id}")
    assert get_response.status_code == 200

    update_response = authenticated_client.put(
        f"/api/v1/cron-jobs/{cron_job_id}",
        json={"name": "Updated Eval Job", "max_runs": 20},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Eval Job"

    toggle_response = authenticated_client.post(f"/api/v1/cron-jobs/{cron_job_id}/toggle")
    assert toggle_response.status_code == 200
    assert toggle_response.json()["status"] == "paused"

    delete_response = authenticated_client.delete(f"/api/v1/cron-jobs/{cron_job_id}")
    assert delete_response.status_code == 204
