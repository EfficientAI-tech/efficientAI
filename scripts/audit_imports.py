"""Audit module imports and route-package re-exports.

Fails loudly on:
  * any importable module that raises on import
  * any name imported from the split route packages that is not exported
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPLIT_PACKAGES = (
    "app.api.v1.routes.call_import_evaluations",
    "app.api.v1.routes.call_imports",
)


def iter_modules() -> list[str]:
    names: list[str] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


def module_import_failures() -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    for name in iter_modules():
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    return failures


def imported_names(path: pathlib.Path) -> list[tuple[str, str, int]]:
    """(module, name, lineno) for absolute imports of a split package."""
    found: list[tuple[str, str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module in SPLIT_PACKAGES:
                for alias in node.names:
                    found.append((node.module, alias.name, node.lineno))
    return found


def reexport_failures() -> list[tuple[str, str, str, int]]:
    failures: list[tuple[str, str, str, int]] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        try:
            refs = imported_names(path)
        except SyntaxError as exc:
            failures.append(("syntax", path.relative_to(ROOT).as_posix(), str(exc), 0))
            continue
        for module, name, lineno in refs:
            pkg = importlib.import_module(module)
            if not hasattr(pkg, name):
                failures.append(
                    (module, path.relative_to(ROOT).as_posix(), name, lineno)
                )
    return failures


def submodule_shadow_entries() -> list[tuple[str, str]]:
    """Names exported by __init__ that point at a submodule, not a function."""
    problems: list[tuple[str, str]] = []
    for module in SPLIT_PACKAGES:
        pkg = importlib.import_module(module)
        for name in dir(pkg):
            if name.startswith("__"):
                continue
            value = getattr(pkg, name)
            if type(value).__name__ == "module":
                problems.append((module, name))
    return problems


def main() -> int:
    print("== module import failures ==")
    mod_failures = module_import_failures()
    for name, err in mod_failures:
        print(f"  FAIL {name}: {err}")
    if not mod_failures:
        print("  none")

    print("== split-package re-export failures ==")
    re_failures = reexport_failures()
    for module, path, name, lineno in re_failures:
        print(f"  FAIL {path}:{lineno} from {module} import {name}")
    if not re_failures:
        print("  none")

    print("== __init__ names that are modules ==")
    shadows = submodule_shadow_entries()
    for module, name in shadows:
        print(f"  WARN {module}.{name} is a module")
    if not shadows:
        print("  none")

    print("== dynamic import() / importlib string literals ==")
    for path in sorted((ROOT / "app").rglob("*.py")):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "importlib.import_module(" in line or "__import__(" in line:
                print(f"  {path.relative_to(ROOT).as_posix()}:{lineno} {line.strip()}")

    return 1 if (mod_failures or re_failures) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
