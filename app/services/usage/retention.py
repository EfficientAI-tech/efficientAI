"""OSS usage rollup retention — per-org flush beyond history window."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from loguru import logger

from app.core.license import get_enabled_features, get_license_info
from app.core.usage_entitlement import OSS_USAGE_HISTORY_DAYS
from app.models.database import LLMUsageDaily


def oss_usage_cutoff_date() -> date:
    return date.today() - timedelta(days=OSS_USAGE_HISTORY_DAYS - 1)


def prune_oss_usage_history(db: Session) -> dict:
    """
    Delete rollup rows older than OSS window for non-entitled orgs.
    Deployment-wide license → no deletes. Org-scoped license → skip licensed org.
    """
    if get_enabled_features() and get_license_info().get("org_id") is None:
        return {"deleted": 0}

    cutoff = oss_usage_cutoff_date()
    licensed_org = get_license_info().get("org_id")

    query = db.query(LLMUsageDaily).filter(LLMUsageDaily.usage_date < cutoff)
    if get_enabled_features() and licensed_org is not None:
        query = query.filter(LLMUsageDaily.organization_id != licensed_org)

    deleted = query.delete(synchronize_session=False)
    db.commit()

    if deleted:
        logger.info("pruned_oss_usage_history deleted_rows={} cutoff={}", deleted, cutoff)

    return {"deleted": deleted, "cutoff": cutoff.isoformat()}
