"""Packaging guards: the SDK must stay installable on its own."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import efficientai_sdk

SRC = Path(efficientai_sdk.__file__).parent
FORBIDDEN_TOP_LEVEL = {"app", "efficientai"}


def test_never_imports_the_platform_or_framework() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in FORBIDDEN_TOP_LEVEL:
                    offenders.append(f"{path.relative_to(SRC)}: {name}")
    assert not offenders, f"SDK must not import platform/framework code: {offenders}"


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+|\.dev\d+)?", efficientai_sdk.__version__)


def test_py_typed_marker_ships() -> None:
    assert (SRC / "py.typed").exists()
