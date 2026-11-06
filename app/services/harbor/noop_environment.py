"""Harbor environment with no sandbox: conversations need no container.

The conversation agent and metric verifier both run in the Harbor host process and
write straight into the trial's host log dirs, so ``mounted=True`` tells Harbor
there is nothing to download back.
"""

from __future__ import annotations

from pathlib import Path

from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.environments.capabilities import EnvironmentCapabilities


class NoopEnvironment(BaseEnvironment):
    @staticmethod
    def type() -> str:
        return "efficientai-noop"

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(mounted=True)

    def _validate_definition(self):
        pass

    async def start(self, force_build: bool) -> None:
        pass

    async def stop(self, delete: bool):
        pass

    async def exec(
        self, command, cwd=None, env=None, timeout_sec=None, user=None, **kwargs
    ) -> ExecResult:
        # Harbor only issues housekeeping commands (mkdir/chmod of /logs dirs) here.
        return ExecResult(stdout="", stderr="", return_code=0)

    async def upload_file(self, source_path: Path | str, target_path: str):
        pass

    async def upload_dir(self, source_dir: Path | str, target_dir: str):
        pass

    async def download_file(self, source_path: str, target_path: Path | str):
        pass

    async def download_dir(self, source_dir: str, target_dir: Path | str):
        pass
