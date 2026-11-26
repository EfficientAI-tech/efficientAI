"""Simulation, suite and result resources."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from efficientai_sdk import APITimeoutError, AsyncEfficientAI, EfficientAI

from .conftest import BASE_URL

RUNS = f"{BASE_URL}/api/v1/simulation-runs"
SUITES = f"{BASE_URL}/api/v1/evaluator-suites"
EVALUATORS = f"{BASE_URL}/api/v1/evaluators"
RESULTS = f"{BASE_URL}/api/v1/evaluator-results"

RUN_ID = "11111111-1111-1111-1111-111111111111"
AGENT_ID = "22222222-2222-2222-2222-222222222222"
SCENARIO_ID = "33333333-3333-3333-3333-333333333333"
PERSONA_ID = "44444444-4444-4444-4444-444444444444"
RESULT_A = "55555555-5555-5555-5555-555555555555"
RESULT_B = "66666666-6666-6666-6666-666666666666"


def client() -> EfficientAI:
    return EfficientAI(api_key="test-key", base_url=BASE_URL, max_retries=0)


def run_payload(status: str = "queued", rate: float | None = None, threshold: float = 0.7) -> dict:
    return {
        "id": RUN_ID,
        "run_id": "123456",
        "agent_id": AGENT_ID,
        "status": status,
        "pass_threshold": threshold,
        "summary": None if rate is None else {"pass_rate": rate},
    }


def result_payload(result_id: str, status: str, passed: bool | None = None) -> dict:
    return {"id": result_id, "result_id": "100001", "status": status, "passed": passed}


@respx.mock
def test_run_get_list_cancel_rerun_and_trials() -> None:
    created = respx.post(RUNS).respond(201, json=run_payload())
    respx.get(f"{RUNS}/{RUN_ID}").respond(200, json=run_payload("running"))
    respx.get(RUNS).respond(200, json=[run_payload("completed", 1.0)])
    respx.post(f"{RUNS}/{RUN_ID}/cancel").respond(200, json=run_payload("cancelled"))
    rerun = respx.post(f"{RUNS}/{RUN_ID}/rerun").respond(201, json=run_payload())
    respx.get(f"{RUNS}/{RUN_ID}/trials").respond(
        200,
        json=[{"id": RESULT_A, "status": "completed", "passed": True, "result_id": "100001"}],
    )
    respx.get(f"{RUNS}/{RUN_ID}/trials/{RESULT_A}").respond(
        200, json={"id": RESULT_A, "status": "completed", "passed": True}
    )
    respx.get(f"{RUNS}/{RUN_ID}/failure-analysis").respond(
        200, json={"failed_trials": 1, "success_rules": {"m": "score >= 0.7"}}
    )
    generated = respx.post(f"{RUNS}/{RUN_ID}/failure-analysis").respond(
        200, json={"failed_trials": 1, "success_rules": {}}
    )

    with client() as sdk:
        run = sdk.simulations.run(
            agent_id=AGENT_ID,
            scenario_ids=[SCENARIO_ID],
            persona_ids=[PERSONA_ID],
            n_attempts=2,
            name="nightly",
        )
        assert run.id == RUN_ID
        assert run.passed is False
        body = json.loads(created.calls.last.request.content)
        assert body == {
            "agent_id": AGENT_ID,
            "scenario_ids": [SCENARIO_ID],
            "persona_ids": [PERSONA_ID],
            "n_attempts": 2,
            "name": "nightly",
        }

        assert sdk.simulations.get(RUN_ID).status == "running"
        listed = sdk.simulations.list(agent_id=AGENT_ID, limit=10)
        assert listed[0].passed is True
        assert sdk.simulations.cancel(RUN_ID).status == "cancelled"
        assert sdk.simulations.rerun(RUN_ID, only_failed=True).status == "queued"
        assert rerun.calls.last.request.url.params["only_failed"] == "true"
        trials = sdk.simulations.trials(RUN_ID)
        assert trials[0].passed is True
        assert sdk.simulations.trial(RUN_ID, RESULT_A).id == RESULT_A
        analysis = sdk.simulations.failure_analysis(RUN_ID)
        assert analysis.failed_trials == 1
        assert analysis.success_rules["m"] == "score >= 0.7"
        sdk.simulations.failure_analysis(RUN_ID, generate=True, model="gpt-4o")
        assert json.loads(generated.calls.last.request.content) == {"model": "gpt-4o"}


@respx.mock
def test_wait_until_completed_passed_and_failed() -> None:
    respx.post(RUNS).respond(201, json=run_payload("queued"))
    respx.get(f"{RUNS}/{RUN_ID}").mock(
        side_effect=[
            httpx.Response(200, json=run_payload("running")),
            httpx.Response(200, json=run_payload("completed", 0.9)),
            httpx.Response(200, json=run_payload("completed", 0.4)),
        ]
    )
    with client() as sdk:
        passed = sdk.simulations.run(
            agent_id=AGENT_ID,
            scenario_ids=[SCENARIO_ID],
            persona_ids=[PERSONA_ID],
        ).wait(timeout=5, interval=0)
        assert passed.status == "completed"
        assert passed.passed is True
        assert passed.summary is not None

        missed = sdk.simulations.get(RUN_ID)
        assert missed.passed is False
        assert missed.wait(timeout=5, interval=0).passed is False


@respx.mock
def test_wait_times_out() -> None:
    respx.get(f"{RUNS}/{RUN_ID}").respond(200, json=run_payload("running"))
    with client() as sdk, pytest.raises(APITimeoutError, match="Timed out after 0s"):
        sdk.simulations.get(RUN_ID).wait(timeout=0, interval=0)


@respx.mock
def test_suite_and_evaluator_wait_polls_results() -> None:
    suite = respx.post(f"{SUITES}/suite-1/run").respond(
        200,
        json={
            "total_runs": 2,
            "task_ids": ["t1", "t2"],
            "evaluator_results": [
                result_payload(RESULT_A, "queued"),
                result_payload(RESULT_B, "queued"),
            ],
        },
    )
    respx.get(f"{RESULTS}/{RESULT_A}").mock(
        side_effect=[
            httpx.Response(200, json=result_payload(RESULT_A, "queued")),
            httpx.Response(200, json=result_payload(RESULT_A, "completed", True)),
        ]
    )
    respx.get(f"{RESULTS}/{RESULT_B}").mock(
        side_effect=[
            httpx.Response(200, json=result_payload(RESULT_B, "running")),
            httpx.Response(200, json=result_payload(RESULT_B, "completed", False)),
        ]
    )
    evaluators = respx.post(f"{EVALUATORS}/run").respond(
        200,
        json={"evaluator_results": [result_payload(RESULT_A, "completed", True)]},
    )
    with client() as sdk:
        finished = sdk.suites.run("suite-1", runs_per_combination=3).wait(timeout=5, interval=0)
        assert json.loads(suite.calls.last.request.content) == {"runs_per_combination": 3}
        assert finished.total_runs == 2
        assert finished.passed is False
        assert finished.pass_rate == 0.5
        assert finished.meets(0.5) is True
        assert finished.meets(0.8) is False

        batch = sdk.evaluators.run([RESULT_A])
        assert json.loads(evaluators.calls.last.request.content) == {"evaluator_ids": [RESULT_A]}
        assert batch.wait(timeout=5, interval=0).passed is True


@respx.mock
def test_result_errors_fail_the_threshold() -> None:
    posted = respx.post(f"{SUITES}/suite-1/run").respond(
        200,
        json={
            "evaluator_results": [
                result_payload(RESULT_A, "completed", True),
                result_payload(RESULT_B, "failed"),
            ]
        },
    )
    with client() as sdk:
        batch = sdk.suites.run("suite-1")
        assert json.loads(posted.calls.last.request.content) == {}
        assert batch.passed is False
        assert batch.meets(0.0) is False


@respx.mock
def test_completed_without_a_pass_flag_does_not_count() -> None:
    respx.post(f"{SUITES}/suite-1/run").respond(
        200,
        json={
            "total_runs": 3,
            "evaluator_results": [
                {
                    "id": RESULT_A,
                    "status": "completed",
                    "metric_scores": {"successful": {"value": False}},
                },
                result_payload(RESULT_B, "completed", True),
            ],
        },
    )
    with client() as sdk:
        batch = sdk.suites.run("suite-1")
        assert batch.pass_rate == pytest.approx(1 / 3)
        assert batch.meets(0.3) is False
    from efficientai_sdk.simulations.models import EvaluatorResult

    bare = EvaluatorResult.model_validate({"id": RESULT_A, "status": "completed"})
    assert bare.succeeded is False


@respx.mock
def test_results_list_get_metrics_and_correlation() -> None:
    respx.get(RESULTS).respond(
        200,
        json={"items": [result_payload(RESULT_A, "completed", True)], "total": 1},
    )
    respx.get(f"{RESULTS}/{RESULT_A}").respond(
        200, json=result_payload(RESULT_A, "completed", True)
    )
    respx.get(f"{RESULTS}/{RESULT_A}/metrics").respond(200, json={"quality": 0.9})
    respx.get(f"{RESULTS}/{RESULT_A}/otel-correlation").respond(
        200, json={"otlp_endpoint": "http://localhost:8000/api/v1/observability/traces"}
    )
    with client() as sdk:
        page = sdk.results.list(suite_id="suite-1", status="completed")
        assert page.total == 1
        assert page.items[0].succeeded is True
        assert sdk.results.get(RESULT_A).id == RESULT_A
        assert sdk.results.metrics(RESULT_A)["quality"] == 0.9
        assert "otlp_endpoint" in sdk.results.otel_correlation(RESULT_A)


@respx.mock
async def test_async_wait() -> None:
    respx.post(RUNS).respond(201, json=run_payload("queued"))
    respx.get(f"{RUNS}/{RUN_ID}").respond(200, json=run_payload("completed", 0.8))
    async with AsyncEfficientAI(api_key="test-key", base_url=BASE_URL, max_retries=0) as sdk:
        run = await sdk.simulations.run(
            agent_id=AGENT_ID,
            scenario_ids=[SCENARIO_ID],
            persona_ids=[PERSONA_ID],
        )
        finished = await run.wait(timeout=5, interval=0)
        assert finished.passed is True
