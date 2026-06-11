"""Apply default workspace capability dependencies to a FastAPI router."""

from __future__ import annotations

from typing import Iterable, Set

from fastapi import Depends
from starlette.routing import BaseRoute

from app.dependencies import require_capability


def apply_workspace_route_capabilities(
    router,
    *,
    view_capability: str,
    manage_capability: str,
    run_capability: str | None = None,
    delete_capability: str | None = None,
    skip_paths: Iterable[str] | None = None,
) -> None:
    """
    Attach capability dependencies to routes on ``router`` based on HTTP method.

    GET/HEAD -> view_capability
    POST/PUT/PATCH -> manage_capability (or run_capability when path ends with /run)
    DELETE -> delete_capability or manage_capability
    """
    skipped = set(skip_paths or ())
    run_paths: Set[str] = set()

    for route in router.routes:
        if not isinstance(route, BaseRoute):
            continue
        path = getattr(route, "path", "") or ""
        if path in skipped:
            continue
        methods = getattr(route, "methods", None) or set()
        deps = list(getattr(route, "dependencies", None) or [])

        if methods <= {"GET", "HEAD"} or (methods & {"GET", "HEAD"} and not methods - {"GET", "HEAD"}):
            deps.append(Depends(require_capability(view_capability)))
        elif "DELETE" in methods:
            cap = delete_capability or manage_capability
            deps.append(Depends(require_capability(cap)))
        elif methods & {"POST", "PUT", "PATCH"}:
            cap = manage_capability
            if run_capability and _looks_like_run_route(path):
                cap = run_capability
            deps.append(Depends(require_capability(cap)))

        route.dependencies = deps


def _looks_like_run_route(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith("/run") or "/run/" in lowered
