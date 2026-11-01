"""Display names for simulation runs (re-run clones)."""

from __future__ import annotations

from typing import Optional


def base_simulation_run_name(name: Optional[str], run_id: str) -> str:
    """Strip stacked ``(re-run)`` / ``(re-run failed)`` suffixes from legacy names."""
    raw = (name or f"Run {run_id}").strip()
    while raw:
        lowered = raw.lower()
        if lowered.endswith(" · failed trials"):
            raw = raw[: -len(" · failed trials")].rstrip()
            continue
        if lowered.endswith(" (re-run failed)"):
            raw = raw[: -len(" (re-run failed)")].rstrip()
            continue
        if lowered.endswith(" (re-run)"):
            raw = raw[: -len(" (re-run)")].rstrip()
            continue
        break
    return raw or f"Run {run_id}"


def simulation_run_name_for_rerun(
    name: Optional[str],
    run_id: str,
    *,
    only_failed: bool = False,
) -> str:
    """Name for a cloned run — same base title; list uses ``run_id`` + started time."""
    base = base_simulation_run_name(name, run_id)
    if only_failed:
        return f"{base} · failed trials"
    return base
