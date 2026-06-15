"""
Workspace capability registry.

Capabilities are fixed strings defined in code. Workspace roles (system or
custom) are bundles of these strings stored in the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Set


# ---------------------------------------------------------------------------
# Capability constants
# ---------------------------------------------------------------------------

CALLS_VIEW = "calls.view"
CALLS_IMPORT = "calls.import"
CALLS_DELETE = "calls.delete"

METRICS_VIEW = "metrics.view"
METRICS_MANAGE = "metrics.manage"

EVALS_VIEW = "evals.view"
EVALS_RUN = "evals.run"

SIM_VIEW = "sim.view"
SIM_MANAGE = "sim.manage"

REPORTS_VIEW = "reports.view"
REPORTS_GENERATE = "reports.generate"

WORKSPACE_SETTINGS = "workspace.settings"
WORKSPACE_MEMBERS_VIEW = "workspace.members.view"
WORKSPACE_MEMBERS_MANAGE = "workspace.members.manage"


ALL_CAPABILITIES: FrozenSet[str] = frozenset(
    {
        CALLS_VIEW,
        CALLS_IMPORT,
        CALLS_DELETE,
        METRICS_VIEW,
        METRICS_MANAGE,
        EVALS_VIEW,
        EVALS_RUN,
        SIM_VIEW,
        SIM_MANAGE,
        REPORTS_VIEW,
        REPORTS_GENERATE,
        WORKSPACE_SETTINGS,
        WORKSPACE_MEMBERS_VIEW,
        WORKSPACE_MEMBERS_MANAGE,
    }
)

VIEW_CAPABILITIES: FrozenSet[str] = frozenset(
    cap for cap in ALL_CAPABILITIES if cap.endswith(".view")
)

EDITOR_EXTRA_CAPABILITIES: FrozenSet[str] = frozenset(
    {
        CALLS_IMPORT,
        METRICS_MANAGE,
        EVALS_RUN,
        SIM_MANAGE,
        REPORTS_GENERATE,
    }
)

ADMIN_EXTRA_CAPABILITIES: FrozenSet[str] = frozenset(
    {
        CALLS_DELETE,
        WORKSPACE_SETTINGS,
        WORKSPACE_MEMBERS_MANAGE,
    }
)

VIEWER_ROLE_CAPABILITIES: List[str] = sorted(VIEW_CAPABILITIES)
EDITOR_ROLE_CAPABILITIES: List[str] = sorted(
    VIEW_CAPABILITIES | EDITOR_EXTRA_CAPABILITIES
)
WORKSPACE_ADMIN_ROLE_CAPABILITIES: List[str] = sorted(ALL_CAPABILITIES)

SYSTEM_ROLE_VIEWER = "Viewer"
SYSTEM_ROLE_EDITOR = "Editor"
SYSTEM_ROLE_ADMIN = "Workspace Admin"


@dataclass(frozen=True)
class CapabilityDomain:
    """Grouping for the role-builder UI."""

    key: str
    label: str
    capabilities: tuple[str, ...]


CAPABILITY_DOMAINS: tuple[CapabilityDomain, ...] = (
    CapabilityDomain("calls", "Calls", (CALLS_VIEW, CALLS_IMPORT, CALLS_DELETE)),
    CapabilityDomain("metrics", "Metrics", (METRICS_VIEW, METRICS_MANAGE)),
    CapabilityDomain("evals", "Evaluations", (EVALS_VIEW, EVALS_RUN)),
    CapabilityDomain("sim", "Simulation", (SIM_VIEW, SIM_MANAGE)),
    CapabilityDomain("reports", "Reports", (REPORTS_VIEW, REPORTS_GENERATE)),
    CapabilityDomain(
        "workspace",
        "Workspace",
        (WORKSPACE_SETTINGS, WORKSPACE_MEMBERS_VIEW, WORKSPACE_MEMBERS_MANAGE),
    ),
)


def normalize_capabilities(raw: List[str] | None) -> Set[str]:
    """Return known capabilities from a role's stored list."""
    if not raw:
        return set()
    return {cap for cap in raw if cap in ALL_CAPABILITIES}


def capabilities_for_registry() -> List[Dict[str, object]]:
    """Serialize the registry for GET /capabilities."""
    return [
        {
            "key": domain.key,
            "label": domain.label,
            "capabilities": [
                {"key": cap, "label": _capability_label(cap)} for cap in domain.capabilities
            ],
        }
        for domain in CAPABILITY_DOMAINS
    ]


def _capability_label(cap: str) -> str:
    action = cap.split(".")[-1].replace("_", " ")
    return action.title()


def required_workspace_role_label(capability: str) -> str:
    """Return the minimum system workspace role that grants *capability*."""
    if capability in ADMIN_EXTRA_CAPABILITIES:
        return SYSTEM_ROLE_ADMIN
    if capability in EDITOR_EXTRA_CAPABILITIES:
        return SYSTEM_ROLE_EDITOR
    return SYSTEM_ROLE_VIEWER


def capability_denied_message(
    capability: str,
    *,
    role_name: str | None = None,
    workspace_label: str = "this workspace",
) -> str:
    """
    User-facing 403 detail when a workspace capability check fails.

    Maps internal capability strings to system role names (Viewer / Editor /
    Workspace Admin) instead of exposing raw capability keys in the UI.
    """
    required_role = required_workspace_role_label(capability)

    if required_role == SYSTEM_ROLE_ADMIN:
        base = (
            f"This action requires the Workspace Admin role in {workspace_label}."
        )
    elif required_role == SYSTEM_ROLE_EDITOR:
        base = (
            f"This action requires at least the Editor role in {workspace_label}."
        )
    else:
        base = f"You don't have permission to perform this action in {workspace_label}."

    if role_name:
        return f"{base} Your current workspace role is {role_name}."
    return f"{base} Ask a workspace admin to upgrade your access."
