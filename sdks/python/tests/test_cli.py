"""``efficientai simulate`` exit codes."""

from __future__ import annotations

import respx

from efficientai_sdk.cli import main

from .conftest import BASE_URL

SUITE = f"{BASE_URL}/api/v1/evaluator-suites/suite-1/run"
RESULT_A = "55555555-5555-5555-5555-555555555555"
RESULT_B = "66666666-6666-6666-6666-666666666666"


def _env(monkeypatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "test-key")
    monkeypatch.setenv("EFFICIENTAI_BASE_URL", BASE_URL)
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")


def _result(result_id: str, status: str, passed: bool | None = None) -> dict:
    return {"id": result_id, "status": status, "passed": passed, "result_id": "100001"}


@respx.mock
def test_cli_exits_0_when_pass_rate_meets_threshold(monkeypatch) -> None:
    _env(monkeypatch)
    respx.post(SUITE).respond(
        200,
        json={
            "evaluator_results": [
                _result(RESULT_A, "completed", True),
                _result(RESULT_B, "completed", True),
            ]
        },
    )
    assert main(["simulate", "--suite", "suite-1", "--fail-under", "0.8", "--timeout", "5"]) == 0


@respx.mock
def test_cli_exits_1_when_pass_rate_is_too_low(monkeypatch) -> None:
    _env(monkeypatch)
    respx.post(SUITE).respond(
        200,
        json={
            "evaluator_results": [
                _result(RESULT_A, "completed", True),
                _result(RESULT_B, "completed", False),
            ]
        },
    )
    assert main(["simulate", "--suite", "suite-1", "--fail-under", "0.8", "--timeout", "5"]) == 1


@respx.mock
def test_cli_exits_1_when_a_result_errors(monkeypatch) -> None:
    _env(monkeypatch)
    respx.post(SUITE).respond(
        200,
        json={"evaluator_results": [_result(RESULT_A, "failed")]},
    )
    assert main(["simulate", "--suite", "suite-1", "--fail-under", "0", "--timeout", "5"]) == 1


@respx.mock
def test_cli_exits_2_on_api_error(monkeypatch) -> None:
    _env(monkeypatch)
    respx.post(SUITE).respond(401, json={"detail": "Invalid API key"})
    assert main(["simulate", "--suite", "suite-1", "--fail-under", "0.8"]) == 2


def test_cli_exits_2_on_bad_usage() -> None:
    assert main(["simulate", "--suite", "suite-1", "--fail-under", "2"]) == 2
    assert main(["simulate"]) == 2
    assert main([]) == 2
