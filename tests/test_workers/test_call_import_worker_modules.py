"""Guardrails for call-import worker helpers that are lazy-imported at runtime."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

_CALL_IMPORT_WORKER_ROOTS = (
    Path("app/workers/tasks"),
    Path("app/workers/concurrency"),
)


def _python_files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


@pytest.mark.parametrize(
    "path",
    [
        p
        for root in _CALL_IMPORT_WORKER_ROOTS
        for p in _python_files_under(root)
    ],
    ids=lambda p: str(p),
)
def test_call_import_worker_python_syntax(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))


def test_platform_call_import_hydrate_exports_hand_off() -> None:
    mod = importlib.import_module("app.workers.tasks.platform_call_import_hydrate")
    assert callable(getattr(mod, "_hand_off", None))
    assert callable(getattr(mod, "hydrate_platform_call_import_row", None))


def test_platform_hydrate_hand_off_is_a_function_def() -> None:
    path = Path("app/workers/tasks/platform_call_import_hydrate.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_hand_off" in names
    assert "hydrate_platform_call_import_row" in names
