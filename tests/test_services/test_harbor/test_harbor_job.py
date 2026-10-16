"""Run a real Harbor job with our agent, environment and verifier (DB legs faked)."""

import asyncio
import json

import pytest

pytest.importorskip("harbor")

from harbor.job import Job  # noqa: E402
from harbor.models.job.config import JobConfig  # noqa: E402

from app.services.harbor.conversation_agent import EfficientAIConversationAgent  # noqa: E402
from app.services.harbor.job_runner import build_job_config, harbor_job_dir  # noqa: E402
from app.services.harbor.metric_verifier import EfficientAIMetricVerifier  # noqa: E402
from app.services.harbor.task_exporter import export_tasks  # noqa: E402


def test_harbor_job_runs_trials_end_to_end(db_session, sim_rows, harbor_work_dir, monkeypatch):
    tasks = export_tasks(
        db_session, run=sim_rows.run, agent=sim_rows.agent, metrics=[sim_rows.metric]
    )
    seen_refs = []

    def _fake_agent_run(self, refs, production_override, test_override):
        seen_refs.append((refs, production_override))
        (self.logs_dir / "trajectory.json").write_text(
            json.dumps(
                {
                    "schema_version": "ATIF-v1.7",
                    "agent": {"name": "efficientai-conversation", "version": "1.0.0"},
                    "steps": [
                        {"step_id": 1, "source": "user", "message": "I want a refund"},
                        {"step_id": 2, "source": "agent", "message": "Sure"},
                    ],
                }
            )
        )
        return {"evaluator_result_id": "fake"}

    def _fake_score(self, trial_name):
        return {"reward": 0.8, "empathy": 0.8}, {"trial": trial_name}

    monkeypatch.setattr(EfficientAIConversationAgent, "_run_sync", _fake_agent_run)
    monkeypatch.setattr(EfficientAIMetricVerifier, "_score_sync", _fake_score)

    sim_rows.run.production_llm_provider = "anthropic"
    sim_rows.run.production_llm_model = "claude-sonnet-5-5"
    config = build_job_config(
        sim_rows.run,
        task_paths=[t.path for t in tasks],
        production_model="anthropic/claude-sonnet-5-5",
    )

    async def _run():
        job = await Job.create(JobConfig.model_validate(config))
        return await job.run()

    result = asyncio.run(_run())

    assert result.stats.n_completed_trials == 2
    assert result.stats.n_errored_trials == 0
    assert len(seen_refs) == 2
    refs, production_override = seen_refs[0]
    assert refs.scenario_id == sim_rows.scenario.id
    assert refs.persona_id == sim_rows.persona.id
    assert refs.trial_name.startswith(tasks[0].name)
    assert len(tasks[0].name) <= 32
    assert production_override.model == "claude-sonnet-5-5"

    trial_dirs = [p for p in harbor_job_dir(sim_rows.run).iterdir() if p.is_dir()]
    assert len(trial_dirs) == 2
    for trial_dir in trial_dirs:
        trial_result = json.loads((trial_dir / "result.json").read_text())
        assert trial_result["verifier_result"]["rewards"] == {"reward": 0.8, "empathy": 0.8}
        assert (trial_dir / "verifier" / "reward-details.json").exists()
