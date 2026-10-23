"""Harbor verifier that scores a trial with the platform's metric LLM judges."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from harbor.models.verifier.result import VerifierResult
from harbor.verifier.base import BaseVerifier

from app.database import SessionLocal
from app.services.harbor.trial_store import score_trial


class EfficientAIMetricVerifier(BaseVerifier):
    """Host-side verifier: never touches the (no-op) environment."""

    def __init__(
        self, *, simulation_run_id: str, pass_threshold: float = 0.7, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.simulation_run_id = UUID(str(simulation_run_id))
        self.pass_threshold = float(pass_threshold)

    async def verify(self) -> VerifierResult:
        trial_name = self.trial_paths.trial_dir.name
        rewards, details = await asyncio.to_thread(self._score_sync, trial_name)
        verifier_dir = self.trial_paths.trial_dir / "verifier"
        verifier_dir.mkdir(parents=True, exist_ok=True)
        (verifier_dir / "reward.json").write_text(json.dumps(rewards, indent=2) + "\n")
        (verifier_dir / "reward-details.json").write_text(
            json.dumps(details, indent=2, default=str) + "\n"
        )
        return VerifierResult(rewards=rewards)

    def _score_sync(self, trial_name: str):
        db = SessionLocal()
        try:
            return score_trial(
                db,
                simulation_run_id=self.simulation_run_id,
                trial_name=trial_name,
                pass_threshold=self.pass_threshold,
            )
        finally:
            db.close()
