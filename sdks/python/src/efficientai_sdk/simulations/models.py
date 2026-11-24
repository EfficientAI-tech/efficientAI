"""Response models for simulations, suite runs and evaluator results."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
TERMINAL_RESULT_STATUSES = frozenset({"completed", "failed"})


def _stringify(value: object) -> object:
    if value is None:
        return None
    return str(value)


class APIModel(BaseModel):
    """Server payload. Unknown fields are kept."""

    model_config = ConfigDict(extra="allow")


class SimulationRunData(APIModel):
    id: str
    status: str
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    pass_threshold: float = 0.7
    summary: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    expected_trials: Optional[int] = None
    completed_trials: Optional[int] = None
    failed_trials: Optional[int] = None

    @field_validator("id", "run_id", "agent_id", mode="before")
    @classmethod
    def _ids(cls, value: object) -> object:
        return _stringify(value)

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @property
    def passed(self) -> bool:
        """True when the run completed and its pass rate meets ``pass_threshold``."""
        if self.status != "completed" or not isinstance(self.summary, dict):
            return False
        rate = self.summary.get("pass_rate")
        if rate is None:
            return False
        try:
            return float(rate) >= float(self.pass_threshold)
        except (TypeError, ValueError):
            return False


class SimulationTrial(APIModel):
    id: str
    status: str
    result_id: Optional[str] = None
    scenario_id: Optional[str] = None
    persona_id: Optional[str] = None
    attempt_index: Optional[int] = None
    reward: Optional[float] = None
    passed: Optional[bool] = None
    error_message: Optional[str] = None

    @field_validator("id", "result_id", "scenario_id", "persona_id", mode="before")
    @classmethod
    def _ids(cls, value: object) -> object:
        return _stringify(value)

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class FailureAnalysis(APIModel):
    failed_trials: int = 0
    success_rules: dict[str, str] = Field(default_factory=dict)


class EvaluatorResult(APIModel):
    id: str
    status: str
    result_id: Optional[str] = None
    passed: Optional[bool] = None
    error_message: Optional[str] = None

    @field_validator("id", "result_id", mode="before")
    @classmethod
    def _ids(cls, value: object) -> object:
        return _stringify(value)

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @property
    def succeeded(self) -> bool:
        """Finished without an error, and was not marked failed by a success rule."""
        return self.status == "completed" and self.passed is not False


class ResultBatchData(APIModel):
    """A suite or evaluator run: one row per queued result, polled until each finishes."""

    total_runs: int = 0
    task_ids: list[str] = Field(default_factory=list)
    phone_call_refs: list[str] = Field(default_factory=list)
    results: list[EvaluatorResult] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_server_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "results" not in data and "evaluator_results" in data:
            data = dict(data)
            data["results"] = data.get("evaluator_results") or []
        return data

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for result in self.results if result.succeeded) / len(self.results)

    @property
    def passed(self) -> bool:
        """True when every result finished successfully."""
        return bool(self.results) and all(result.succeeded for result in self.results)

    def meets(self, threshold: float) -> bool:
        """True when no result errored and the pass rate is at least ``threshold``."""
        if any(result.status == "failed" for result in self.results):
            return False
        return self.pass_rate >= threshold


class EvaluatorResultPage(APIModel):
    items: list[EvaluatorResult] = Field(default_factory=list)
    total: int = 0
    usage_cost_usd: Optional[float] = None
