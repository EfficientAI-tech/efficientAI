"""Harbor agent that runs a test-agent ↔ production-agent conversation.

External ``BaseAgent``: the loop runs in the Harbor host process (no sandbox) and
reuses the platform's LLM-to-LLM simulation. Harbor's built-in simulated user
(``--user-agent --bridge acp``) only targets coding agents, so this agent drives
both legs itself.
"""

from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path
from uuid import UUID

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.options import AgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.config import TrialConfig

from app.database import SessionLocal
from app.services.harbor.trial_store import (
    TRAJECTORY_AGENT_NAME,
    TRAJECTORY_AGENT_VERSION,
    TrialRefs,
    llm_override,
    run_trial_conversation,
)


class ConversationAgentOptions(AgentOptions):
    simulation_run_id: str
    production_llm_provider: str | None = None
    production_llm_model: str | None = None
    test_llm_provider: str | None = None
    test_llm_model: str | None = None


def task_metadata_for_trial(trial_dir: Path) -> dict:
    """Read our ``[metadata]`` from the trial's task.toml (Harbor only passes the instruction)."""
    config = TrialConfig.model_validate_json((trial_dir / "config.json").read_text())
    if config.task.path is None:
        raise ValueError("Simulation trials must use local task paths")
    with open(Path(config.task.path) / "task.toml", "rb") as fh:
        return tomllib.load(fh).get("metadata", {})


class EfficientAIConversationAgent(BaseAgent):
    capabilities = AgentCapabilities(atif=True)
    options_model = ConversationAgentOptions

    @staticmethod
    def name() -> str:
        return TRAJECTORY_AGENT_NAME

    def version(self) -> str | None:
        return TRAJECTORY_AGENT_VERSION

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        options: ConversationAgentOptions = self.options  # type: ignore[assignment]
        trial_dir = self.logs_dir.parent
        metadata = task_metadata_for_trial(trial_dir)
        refs = TrialRefs(
            simulation_run_id=UUID(options.simulation_run_id),
            scenario_id=UUID(metadata["scenario_id"]),
            persona_id=UUID(metadata["persona_id"]),
            trial_name=trial_dir.name,
        )
        # Sync DB + LLM calls run in a worker thread so Harbor keeps trials concurrent.
        outcome = await asyncio.to_thread(
            self._run_sync,
            refs,
            llm_override(options.production_llm_provider, options.production_llm_model),
            llm_override(options.test_llm_provider, options.test_llm_model),
        )
        context.metadata = outcome

    def _run_sync(self, refs, production_override, test_override) -> dict:
        db = SessionLocal()
        try:
            return run_trial_conversation(
                db,
                refs=refs,
                trajectory_path=self.logs_dir / "trajectory.json",
                production_override=production_override,
                test_override=test_override,
            )
        finally:
            db.close()
