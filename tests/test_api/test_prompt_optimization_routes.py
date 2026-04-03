"""API tests for prompt-optimization routes."""


def test_create_list_get_delete_optimization_run(authenticated_client, make_agent):
    agent = make_agent(description="Optimize this prompt")

    payload = {
        "agent_id": str(agent.id),
        "config": {"max_iterations": 2},
    }
    create_response = authenticated_client.post("/api/v1/prompt-optimization/runs", json=payload)
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]

    list_response = authenticated_client.get("/api/v1/prompt-optimization/runs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/prompt-optimization/runs/{run_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == run_id

    delete_response = authenticated_client.delete(f"/api/v1/prompt-optimization/runs/{run_id}")
    assert delete_response.status_code == 204


def test_accept_candidate(authenticated_client, make_agent, make_prompt_optimization_run, make_prompt_optimization_candidate):
    agent = make_agent(description="Optimize me")
    run = make_prompt_optimization_run(agent_id=agent.id)
    candidate = make_prompt_optimization_candidate(optimization_run_id=run.id, is_accepted=False)

    response = authenticated_client.post(
        f"/api/v1/prompt-optimization/runs/{run.id}/candidates/{candidate.id}/accept"
    )

    assert response.status_code == 200
    assert response.json()["candidate_id"] == str(candidate.id)
