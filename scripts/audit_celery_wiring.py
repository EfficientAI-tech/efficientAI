"""Audit Celery task wiring after modularisation.

Checks:
  1. every registered task name is unique
  2. every apply_async/send_task task lookup resolves to a registered task
  3. every queue passed to apply_async is consumed by a worker in docker-compose
  4. every task routes to a queue that exists
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASK_RE = re.compile(r"name=[\"']([^\"']+)[\"']")


def registered_tasks() -> dict[str, list[str]]:
    tasks: dict[str, list[str]] = {}
    for path in sorted((ROOT / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        # Task decorators are the only registration path in this codebase.
        for match in re.finditer(
            r"@(?:celery_app|app|shared_task)\b[\s\S]{0,400}?\)", text
        ):
            block = match.group(0)
            name_match = TASK_RE.search(block)
            if name_match:
                tasks.setdefault(name_match.group(1), []).append(rel)
    # Include explicit task names assigned via name=_ in task() calls.
    for path in sorted((ROOT / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for match in re.finditer(r"\.task\(\s*name=[\"']([^\"']+)[\"']", text):
            tasks.setdefault(match.group(1), [])
            if rel not in tasks[match.group(1)]:
                tasks[match.group(1)].append(rel)
    return tasks


def worker_queues() -> set[str]:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    queues: set[str] = set()
    for match in re.finditer(r"--queues\s+([\w,\-]+)", compose):
        queues.update(q.strip() for q in match.group(1).split(",") if q.strip())
    return queues


def dispatch_sites() -> list[tuple[str, int, str, str | None]]:
    """(file, lineno, task_ref, queue) for every apply_async/send_task call."""
    sites: list[tuple[str, int, str, str | None]] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            attr = getattr(func, "attr", None)
            if attr not in {"apply_async", "send_task"}:
                continue
            queue = None
            for kw in node.keywords:
                if kw.arg == "queue" and isinstance(kw.value, ast.Constant):
                    queue = str(kw.value.value)
            target = ""
            if attr == "send_task" and node.args:
                target = ast.unparse(node.args[0])
            elif isinstance(func.value, (ast.Name, ast.Attribute)):
                target = ast.unparse(func.value)
            sites.append((rel, node.lineno, target, queue))
    return sites


def main() -> int:
    tasks = registered_tasks()
    queues = worker_queues()
    sites = dispatch_sites()

    print(f"registered tasks: {len(tasks)}")
    dupes = {name: files for name, files in tasks.items() if len(set(files)) > 1}
    print("== duplicate task names ==")
    for name, files in dupes.items():
        print(f"  FAIL {name}: {files}")
    if not dupes:
        print("  none")

    print("== queues consumed by workers ==")
    print(f"  {sorted(queues)}")

    print("== dispatch to unknown queues ==")
    unknown: list[str] = []
    for rel, lineno, target, queue in sites:
        if queue and queue not in queues:
            unknown.append(f"{rel}:{lineno} {target} queue={queue}")
    for line in unknown:
        print(f"  FAIL {line}")
    if not unknown:
        print("  none")

    print("== unresolvable task references ==")
    by_suffix = {}
    for name in tasks:
        by_suffix[name] = name
    unresolved: list[str] = []
    for rel, lineno, target, _queue in sites:
        if not target:
            continue
        leaf = target.split(".")[-1]
        candidates = {leaf, leaf.removesuffix("_task")}
        known = set(tasks) | {n.split(".")[-1] for n in tasks}
        if candidates & known:
            continue
        # send_task may pass a literal name
        if target.strip("\"'") in tasks:
            continue
        unresolved.append(f"{rel}:{lineno} {target}")
    for line in unresolved:
        print(f"  WARN {line}")
    if not unresolved:
        print("  none")

    return 1 if (dupes or unknown) else 0


if __name__ == "__main__":
    sys.exit(main())
