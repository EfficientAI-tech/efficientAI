"""Enterprise entitlement for usage history (any catalog feature, not per-feature gates)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.core.license import get_enabled_features, get_license_info

OSS_USAGE_HISTORY_DAYS = 7


@dataclass(frozen=True)
class UsagePolicySnapshot:
    extended_history: bool
    max_history_days: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "extended_history": self.extended_history,
            "max_history_days": self.max_history_days,
        }


def has_enterprise_entitlement(organization_id: Optional[UUID] = None) -> bool:
    """Valid license with at least one catalog feature; org-scoped licenses must match."""
    if not get_enabled_features():
        return False

    info = get_license_info()
    licensed_org = info.get("org_id")
    if licensed_org is None:
        return True

    if organization_id is None:
        return False

    return str(organization_id) == str(licensed_org)


def deployment_has_entitlement() -> bool:
    """Deployment-wide entitlement (license without org_id scoping)."""
    if not get_enabled_features():
        return False
    return get_license_info().get("org_id") is None


def get_usage_policy(organization_id: UUID) -> UsagePolicySnapshot:
    if has_enterprise_entitlement(organization_id):
        return UsagePolicySnapshot(extended_history=True, max_history_days=None)
    return UsagePolicySnapshot(
        extended_history=False,
        max_history_days=OSS_USAGE_HISTORY_DAYS,
    )
