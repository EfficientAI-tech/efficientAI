"""Sync and async resources for simulations, suites, evaluators and results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from pydantic import PrivateAttr

from efficientai_sdk._base_client import AsyncAPIClient, SyncAPIClient
from efficientai_sdk._exceptions import ConfigurationError, EfficientAIError
from efficientai_sdk.simulations.models import (
    TERMINAL_RESULT_STATUSES,
    TERMINAL_RUN_STATUSES,
    EvaluatorResult,
    EvaluatorResultPage,
    FailureAnalysis,
    ResultBatchData,
    SimulationRunData,
    SimulationTrial,
)
from efficientai_sdk.simulations.polling import poll_async, poll_sync

RUNS_PATH = "/api/v1/simulation-runs"
SUITES_PATH = "/api/v1/evaluator-suites"
EVALUATORS_PATH = "/api/v1/evaluators"
RESULTS_PATH = "/api/v1/evaluator-results"


def _compact(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _ids(values: Sequence[object]) -> list[str]:
    return [str(value) for value in values]


def _expect_dict(payload: Any, what: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    raise EfficientAIError(f"Unexpected {what} response from the server.")


def _expect_list(payload: Any, what: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    raise EfficientAIError(f"Unexpected {what} response from the server.")


class SimulationRun(SimulationRunData):
    """One simulation run, bound to a sync client so :meth:`wait` can refresh it."""

    _get: Any = PrivateAttr(default=None)

    def wait(self, *, timeout: float = 1800, interval: float = 2.0) -> SimulationRun:
        """Block until the run is completed, failed or cancelled.

        Returns the latest run. A finished run that missed its threshold still
        returns; check :attr:`passed`. Raises ``APITimeoutError`` on timeout.
        """
        if self._get is None:
            raise ConfigurationError("This run is not bound to a client.")
        return poll_sync(
            self,
            self._get,
            lambda run: run.status in TERMINAL_RUN_STATUSES,
            timeout=timeout,
            interval=interval,
        )


class AsyncSimulationRun(SimulationRunData):
    """Async form of :class:`SimulationRun`."""

    _get: Any = PrivateAttr(default=None)

    async def wait(self, *, timeout: float = 1800, interval: float = 2.0) -> AsyncSimulationRun:
        """Async form of :meth:`SimulationRun.wait`."""
        if self._get is None:
            raise ConfigurationError("This run is not bound to a client.")
        return await poll_async(
            self,
            self._get,
            lambda run: run.status in TERMINAL_RUN_STATUSES,
            timeout=timeout,
            interval=interval,
        )


class ResultBatch(ResultBatchData):
    """Suite or evaluator run handle for the sync client."""

    _refresh: Any = PrivateAttr(default=None)

    def wait(self, *, timeout: float = 1800, interval: float = 2.0) -> ResultBatch:
        """Block until every evaluator result is completed or failed."""
        if self._refresh is None:
            raise ConfigurationError("This run is not bound to a client.")
        return poll_sync(
            self,
            self._refresh,
            _batch_done,
            timeout=timeout,
            interval=interval,
        )


class AsyncResultBatch(ResultBatchData):
    """Async form of :class:`ResultBatch`."""

    _refresh: Any = PrivateAttr(default=None)

    async def wait(self, *, timeout: float = 1800, interval: float = 2.0) -> AsyncResultBatch:
        """Async form of :meth:`ResultBatch.wait`."""
        if self._refresh is None:
            raise ConfigurationError("This run is not bound to a client.")
        return await poll_async(
            self,
            self._refresh,
            _batch_done,
            timeout=timeout,
            interval=interval,
        )


def _batch_done(batch: ResultBatchData) -> bool:
    if not batch.results:
        return True
    return all(result.status in TERMINAL_RESULT_STATUSES for result in batch.results)


def _bind_run(client: SyncAPIClient, payload: dict[str, Any]) -> SimulationRun:
    run = SimulationRun.model_validate(payload)

    def getter() -> SimulationRun:
        body = _expect_dict(client.request("GET", f"{RUNS_PATH}/{run.id}"), "simulation run")
        return _bind_run(client, body)

    run._get = getter
    return run


def _bind_async_run(client: AsyncAPIClient, payload: dict[str, Any]) -> AsyncSimulationRun:
    run = AsyncSimulationRun.model_validate(payload)

    async def getter() -> AsyncSimulationRun:
        body = _expect_dict(
            await client.request("GET", f"{RUNS_PATH}/{run.id}"),
            "simulation run",
        )
        return _bind_async_run(client, body)

    run._get = getter
    return run


def _bind_batch(client: SyncAPIClient, payload: dict[str, Any]) -> ResultBatch:
    batch = ResultBatch.model_validate(payload)
    ids = [result.id for result in batch.results]

    def refresh() -> ResultBatch:
        results = []
        for result_id in ids:
            body = client.request("GET", f"{RESULTS_PATH}/{result_id}")
            results.append(EvaluatorResult.model_validate(_expect_dict(body, "evaluator result")))
        nxt = ResultBatch.model_validate(
            {
                "total_runs": batch.total_runs,
                "task_ids": list(batch.task_ids),
                "phone_call_refs": list(batch.phone_call_refs),
                "results": [item.model_dump() for item in results],
            }
        )
        nxt._refresh = refresh
        return nxt

    batch._refresh = refresh
    return batch


def _bind_async_batch(client: AsyncAPIClient, payload: dict[str, Any]) -> AsyncResultBatch:
    batch = AsyncResultBatch.model_validate(payload)
    ids = [result.id for result in batch.results]

    async def refresh() -> AsyncResultBatch:
        results = []
        for result_id in ids:
            body = _expect_dict(
                await client.request("GET", f"{RESULTS_PATH}/{result_id}"),
                "evaluator result",
            )
            results.append(EvaluatorResult.model_validate(body))
        nxt = AsyncResultBatch.model_validate(
            {
                "total_runs": batch.total_runs,
                "task_ids": list(batch.task_ids),
                "phone_call_refs": list(batch.phone_call_refs),
                "results": [item.model_dump() for item in results],
            }
        )
        nxt._refresh = refresh
        return nxt

    batch._refresh = refresh
    return batch


def _run_body(
    *,
    agent_id: object,
    scenario_ids: Sequence[object],
    persona_ids: Sequence[object],
    n_attempts: int,
    name: Optional[str],
    metric_ids: Optional[Sequence[object]],
    n_concurrent: Optional[int],
    pass_threshold: Optional[float],
) -> dict[str, Any]:
    return _compact(
        {
            "agent_id": str(agent_id),
            "scenario_ids": _ids(scenario_ids),
            "persona_ids": _ids(persona_ids),
            "n_attempts": n_attempts,
            "name": name,
            "metric_ids": _ids(metric_ids) if metric_ids is not None else None,
            "n_concurrent": n_concurrent,
            "pass_threshold": pass_threshold,
        }
    )


def _suite_body(
    *,
    runs_per_combination: Optional[int] = 1,
    to_number: Optional[str] = None,
    from_number: Optional[str] = None,
) -> dict[str, Any]:
    return _compact(
        {
            "runs_per_combination": runs_per_combination,
            "to_number": to_number,
            "from_number": from_number,
        }
    )


def _analysis_body(
    *,
    provider: Optional[str],
    model: Optional[str],
) -> dict[str, Any]:
    return _compact({"provider": provider, "model": model})


class SimulationsResource:
    """``client.simulations``: create a run and read it back."""

    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client

    def run(
        self,
        *,
        agent_id: object,
        scenario_ids: Sequence[object],
        persona_ids: Sequence[object],
        n_attempts: int = 1,
        name: Optional[str] = None,
        metric_ids: Optional[Sequence[object]] = None,
        n_concurrent: Optional[int] = None,
        pass_threshold: Optional[float] = None,
    ) -> SimulationRun:
        """Start a simulation and return the queued run."""
        payload = self._client.request(
            "POST",
            RUNS_PATH,
            json=_run_body(
                agent_id=agent_id,
                scenario_ids=scenario_ids,
                persona_ids=persona_ids,
                n_attempts=n_attempts,
                name=name,
                metric_ids=metric_ids,
                n_concurrent=n_concurrent,
                pass_threshold=pass_threshold,
            ),
        )
        return _bind_run(self._client, _expect_dict(payload, "simulation run"))

    def get(self, run_id: object) -> SimulationRun:
        payload = self._client.request("GET", f"{RUNS_PATH}/{run_id}")
        return _bind_run(self._client, _expect_dict(payload, "simulation run"))

    def list(
        self,
        *,
        agent_id: Optional[object] = None,
        limit: Optional[int] = None,
    ) -> list[SimulationRun]:
        payload = self._client.request(
            "GET",
            RUNS_PATH,
            params=_compact({"agent_id": str(agent_id) if agent_id else None, "limit": limit}),
        )
        return [
            _bind_run(self._client, item)
            for item in _expect_list(payload, "simulation run list")
            if isinstance(item, dict)
        ]

    def cancel(self, run_id: object) -> SimulationRun:
        payload = self._client.request("POST", f"{RUNS_PATH}/{run_id}/cancel")
        return _bind_run(self._client, _expect_dict(payload, "simulation run"))

    def rerun(self, run_id: object, *, only_failed: bool = False) -> SimulationRun:
        payload = self._client.request(
            "POST",
            f"{RUNS_PATH}/{run_id}/rerun",
            params={"only_failed": only_failed},
        )
        return _bind_run(self._client, _expect_dict(payload, "simulation run"))

    def trials(self, run_id: object) -> Sequence[SimulationTrial]:
        payload = self._client.request("GET", f"{RUNS_PATH}/{run_id}/trials")
        return [
            SimulationTrial.model_validate(item)
            for item in _expect_list(payload, "trial list")
            if isinstance(item, dict)
        ]

    def trial(self, run_id: object, trial_id: object) -> SimulationTrial:
        payload = self._client.request("GET", f"{RUNS_PATH}/{run_id}/trials/{trial_id}")
        return SimulationTrial.model_validate(_expect_dict(payload, "trial"))

    def failure_analysis(
        self,
        run_id: object,
        *,
        generate: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> FailureAnalysis:
        """Return the cached analysis, or start a new one when ``generate`` is set."""
        path = f"{RUNS_PATH}/{run_id}/failure-analysis"
        if generate:
            payload = self._client.request(
                "POST",
                path,
                json=_analysis_body(provider=provider, model=model),
            )
        else:
            payload = self._client.request("GET", path)
        return FailureAnalysis.model_validate(_expect_dict(payload, "failure analysis"))


class AsyncSimulationsResource:
    """``await`` form of :class:`SimulationsResource`."""

    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client

    async def run(
        self,
        *,
        agent_id: object,
        scenario_ids: Sequence[object],
        persona_ids: Sequence[object],
        n_attempts: int = 1,
        name: Optional[str] = None,
        metric_ids: Optional[Sequence[object]] = None,
        n_concurrent: Optional[int] = None,
        pass_threshold: Optional[float] = None,
    ) -> AsyncSimulationRun:
        payload = await self._client.request(
            "POST",
            RUNS_PATH,
            json=_run_body(
                agent_id=agent_id,
                scenario_ids=scenario_ids,
                persona_ids=persona_ids,
                n_attempts=n_attempts,
                name=name,
                metric_ids=metric_ids,
                n_concurrent=n_concurrent,
                pass_threshold=pass_threshold,
            ),
        )
        return _bind_async_run(self._client, _expect_dict(payload, "simulation run"))

    async def get(self, run_id: object) -> AsyncSimulationRun:
        payload = await self._client.request("GET", f"{RUNS_PATH}/{run_id}")
        return _bind_async_run(self._client, _expect_dict(payload, "simulation run"))

    async def list(
        self,
        *,
        agent_id: Optional[object] = None,
        limit: Optional[int] = None,
    ) -> list[AsyncSimulationRun]:
        payload = await self._client.request(
            "GET",
            RUNS_PATH,
            params=_compact({"agent_id": str(agent_id) if agent_id else None, "limit": limit}),
        )
        return [
            _bind_async_run(self._client, item)
            for item in _expect_list(payload, "simulation run list")
            if isinstance(item, dict)
        ]

    async def cancel(self, run_id: object) -> AsyncSimulationRun:
        payload = await self._client.request("POST", f"{RUNS_PATH}/{run_id}/cancel")
        return _bind_async_run(self._client, _expect_dict(payload, "simulation run"))

    async def rerun(self, run_id: object, *, only_failed: bool = False) -> AsyncSimulationRun:
        payload = await self._client.request(
            "POST",
            f"{RUNS_PATH}/{run_id}/rerun",
            params={"only_failed": only_failed},
        )
        return _bind_async_run(self._client, _expect_dict(payload, "simulation run"))

    async def trials(self, run_id: object) -> Sequence[SimulationTrial]:
        payload = await self._client.request("GET", f"{RUNS_PATH}/{run_id}/trials")
        return [
            SimulationTrial.model_validate(item)
            for item in _expect_list(payload, "trial list")
            if isinstance(item, dict)
        ]

    async def trial(self, run_id: object, trial_id: object) -> SimulationTrial:
        payload = await self._client.request("GET", f"{RUNS_PATH}/{run_id}/trials/{trial_id}")
        return SimulationTrial.model_validate(_expect_dict(payload, "trial"))

    async def failure_analysis(
        self,
        run_id: object,
        *,
        generate: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> FailureAnalysis:
        path = f"{RUNS_PATH}/{run_id}/failure-analysis"
        if generate:
            payload = await self._client.request(
                "POST", path, json=_analysis_body(provider=provider, model=model)
            )
        else:
            payload = await self._client.request("GET", path)
        return FailureAnalysis.model_validate(_expect_dict(payload, "failure analysis"))


class SuitesResource:
    """``client.suites``: run every combination in a suite."""

    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client

    def run(
        self,
        suite_id: object,
        *,
        runs_per_combination: Optional[int] = None,
        to_number: Optional[str] = None,
        from_number: Optional[str] = None,
    ) -> ResultBatch:
        payload = self._client.request(
            "POST",
            f"{SUITES_PATH}/{suite_id}/run",
            json=_suite_body(
                runs_per_combination=runs_per_combination,
                to_number=to_number,
                from_number=from_number,
            ),
        )
        return _bind_batch(self._client, _expect_dict(payload, "suite run"))


class AsyncSuitesResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client

    async def run(
        self,
        suite_id: object,
        *,
        runs_per_combination: Optional[int] = None,
        to_number: Optional[str] = None,
        from_number: Optional[str] = None,
    ) -> AsyncResultBatch:
        payload = await self._client.request(
            "POST",
            f"{SUITES_PATH}/{suite_id}/run",
            json=_suite_body(
                runs_per_combination=runs_per_combination,
                to_number=to_number,
                from_number=from_number,
            ),
        )
        return _bind_async_batch(self._client, _expect_dict(payload, "suite run"))


class EvaluatorsResource:
    """``client.evaluators``: run specific evaluators."""

    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client

    def run(self, evaluator_ids: Sequence[object]) -> ResultBatch:
        payload = self._client.request(
            "POST",
            f"{EVALUATORS_PATH}/run",
            json={"evaluator_ids": _ids(evaluator_ids)},
        )
        return _bind_batch(self._client, _expect_dict(payload, "evaluator run"))


class AsyncEvaluatorsResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client

    async def run(self, evaluator_ids: Sequence[object]) -> AsyncResultBatch:
        payload = await self._client.request(
            "POST",
            f"{EVALUATORS_PATH}/run",
            json={"evaluator_ids": _ids(evaluator_ids)},
        )
        return _bind_async_batch(self._client, _expect_dict(payload, "evaluator run"))


class ResultsResource:
    """``client.results``: read evaluator results."""

    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client

    def list(
        self,
        *,
        agent_id: Optional[object] = None,
        suite_id: Optional[object] = None,
        evaluator_id: Optional[object] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> EvaluatorResultPage:
        payload = self._client.request(
            "GET",
            RESULTS_PATH,
            params=_compact(
                {
                    "agent_id": str(agent_id) if agent_id else None,
                    "suite_id": str(suite_id) if suite_id else None,
                    "evaluator_id": str(evaluator_id) if evaluator_id else None,
                    "status": status,
                    "limit": limit,
                    "skip": skip,
                }
            ),
        )
        return EvaluatorResultPage.model_validate(_expect_dict(payload, "evaluator result list"))

    def get(self, result_id: object) -> EvaluatorResult:
        payload = self._client.request("GET", f"{RESULTS_PATH}/{result_id}")
        return EvaluatorResult.model_validate(_expect_dict(payload, "evaluator result"))

    def metrics(self, result_id: object) -> dict[str, Any]:
        payload = self._client.request("GET", f"{RESULTS_PATH}/{result_id}/metrics")
        return _expect_dict(payload, "evaluator result metrics")

    def otel_correlation(self, result_id: object) -> dict[str, Any]:
        payload = self._client.request("GET", f"{RESULTS_PATH}/{result_id}/otel-correlation")
        return _expect_dict(payload, "otel correlation")


class AsyncResultsResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client

    async def list(
        self,
        *,
        agent_id: Optional[object] = None,
        suite_id: Optional[object] = None,
        evaluator_id: Optional[object] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> EvaluatorResultPage:
        payload = await self._client.request(
            "GET",
            RESULTS_PATH,
            params=_compact(
                {
                    "agent_id": str(agent_id) if agent_id else None,
                    "suite_id": str(suite_id) if suite_id else None,
                    "evaluator_id": str(evaluator_id) if evaluator_id else None,
                    "status": status,
                    "limit": limit,
                    "skip": skip,
                }
            ),
        )
        return EvaluatorResultPage.model_validate(_expect_dict(payload, "evaluator result list"))

    async def get(self, result_id: object) -> EvaluatorResult:
        payload = await self._client.request("GET", f"{RESULTS_PATH}/{result_id}")
        return EvaluatorResult.model_validate(_expect_dict(payload, "evaluator result"))

    async def metrics(self, result_id: object) -> dict[str, Any]:
        payload = await self._client.request("GET", f"{RESULTS_PATH}/{result_id}/metrics")
        return _expect_dict(payload, "evaluator result metrics")

    async def otel_correlation(self, result_id: object) -> dict[str, Any]:
        payload = await self._client.request("GET", f"{RESULTS_PATH}/{result_id}/otel-correlation")
        return _expect_dict(payload, "otel correlation")


__all__ = [
    "AsyncEvaluatorsResource",
    "AsyncResultBatch",
    "AsyncResultsResource",
    "AsyncSimulationRun",
    "AsyncSimulationsResource",
    "AsyncSuitesResource",
    "EvaluatorsResource",
    "ResultBatch",
    "ResultsResource",
    "SimulationRun",
    "SimulationsResource",
    "SuitesResource",
]
