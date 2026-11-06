"""Audit frontend API calls against the FastAPI route table.

Extracts every ``/api/...`` literal (including template literals) from the
frontend and checks it can be matched by a registered backend route with the
same method. Template placeholders (``${...}``) are treated as path params.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = ROOT / "frontend" / "src"

CALL_RE = re.compile(
    r"(?P<client>axios|this\.client)\s*\.\s*(?P<method>get|post|put|patch|delete)\s*\("
    r"\s*(?P<q>[`'\"])(?P<path>.*?)(?P=q)",
    re.S,
)
# this.client.get(url, {...}) style is covered above; also catch template-only
TEMPLATE_RE = re.compile(r"`(?P<path>/api/[^`]*)`")


def normalize(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"/+", "/", path)
    return path.rstrip("/") or "/"


def frontend_calls() -> list[tuple[str, int, str, str]]:
    calls: list[tuple[str, int, str, str]] = []
    for path in sorted(FRONTEND_SRC.rglob("*.ts")) + sorted(
        FRONTEND_SRC.rglob("*.tsx")
    ):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in CALL_RE.finditer(text):
            raw = match.group("path")
            if "/api/" not in raw:
                continue
            line = text[: match.start()].count("\n") + 1
            calls.append((rel, line, match.group("method").upper(), normalize(raw)))
    return calls


def backend_routes() -> set[tuple[str, str]]:
    from app.main import create_app

    app = create_app()
    routes: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not path.startswith("/api"):
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            routes.add((method, path))
    return routes


def route_matches(method: str, path: str, routes: set[tuple[str, str]]) -> bool:
    segs = [s for s in path.strip("/").split("/") if s]
    for rmethod, rpath in routes:
        if rmethod != method:
            continue
        rsegs = [s for s in rpath.strip("/").split("/") if s]
        if len(rsegs) != len(segs):
            continue
        ok = True
        for want, got in zip(segs, rsegs):
            if got.startswith("{") or got == "{}":
                continue
            if want == "{}":
                continue
            if want != got:
                ok = False
                break
        if ok:
            return True
    return False


def main() -> int:
    routes = backend_routes()
    calls = frontend_calls()
    print(f"backend routes: {len(routes)}  frontend calls: {len(calls)}")

    # A path found in the file might pair with several methods; report the
    # distinct ones.
    unmatched_paths: dict[str, set[str]] = {}
    for rel, line, method, path in calls:
        if not route_matches(method, path, routes):
            unmatched_paths.setdefault(f"{method} {path}", set()).add(f"{rel}:{line}")

    print("== frontend calls with no matching backend route ==")
    for key in sorted(unmatched_paths):
        sites = sorted(unmatched_paths[key])[:3]
        print(f"  FAIL {key}  ({', '.join(sites)})")
    if not unmatched_paths:
        print("  none")
    return 1 if unmatched_paths else 0


if __name__ == "__main__":
    sys.exit(main())
