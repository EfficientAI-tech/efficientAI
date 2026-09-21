"""Open-source quantity limits for organizations without enterprise entitlement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.usage_entitlement import has_enterprise_entitlement
from app.models.database import Agent, Metric, OrganizationMember, Workspace

OSS_MAX_USER_METRICS = 5
OSS_MAX_AGENTS = 3
OSS_MAX_ORG_MEMBERS = 1
OSS_MAX_WORKSPACES = 1

OssQuotaResource = Literal["metrics", "agents", "org_members", "workspaces"]

_RESOURCE_LIMITS: dict[OssQuotaResource, int] = {
    "metrics": OSS_MAX_USER_METRICS,
    "agents": OSS_MAX_AGENTS,
    "org_members": OSS_MAX_ORG_MEMBERS,
    "workspaces": OSS_MAX_WORKSPACES,
}

_RESOURCE_MESSAGES: dict[OssQuotaResource, str] = {
    "metrics": (
        "Open source deployments are limited to "
        f"{OSS_MAX_USER_METRICS} user-created metrics per organization. "
        "Seeded default metrics do not count toward this limit."
    ),
    "agents": (
        f"Open source deployments are limited to {OSS_MAX_AGENTS} agents "
        "per organization."
    ),
    "org_members": (
        f"Open source deployments are limited to {OSS_MAX_ORG_MEMBERS} "
        "organization member (solo use). Invite additional users with an "
        "Enterprise license."
    ),
    "workspaces": (
        f"Open source deployments are limited to {OSS_MAX_WORKSPACES} "
        "workspace (the default workspace)."
    ),
}


@dataclass(frozen=True)
class OssQuotasSnapshot:
    max_user_metrics: Optional[int]
    max_agents: Optional[int]
    max_org_members: Optional[int]
    max_workspaces: Optional[int]

    def as_dict(self) -> dict:
        return {
            "max_user_metrics": self.max_user_metrics,
            "max_agents": self.max_agents,
            "max_org_members": self.max_org_members,
            "max_workspaces": self.max_workspaces,
        }


@dataclass(frozen=True)
class OssQuotaUsageSnapshot:
    user_metrics: int
    agents: int
    org_members: int
    workspaces: int

    def as_dict(self) -> dict:
        return {
            "user_metrics": self.user_metrics,
            "agents": self.agents,
            "org_members": self.org_members,
            "workspaces": self.workspaces,
        }


def _user_metric_filter(organization_id: UUID):
    return and_(
        Metric.organization_id == organization_id,
        Metric.is_default.is_(False),
        or_(
            Metric.metric_origin.is_(None),
            Metric.metric_origin != "default",
        ),
    )


def count_user_metrics(db: Session, organization_id: UUID) -> int:
    return (
        db.query(Metric)
        .filter(_user_metric_filter(organization_id))
        .count()
    )


def count_agents(db: Session, organization_id: UUID) -> int:
    return (
        db.query(Agent)
        .filter(Agent.organization_id == organization_id)
        .count()
    )


def count_org_members(db: Session, organization_id: UUID) -> int:
    return (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == organization_id)
        .count()
    )


def count_workspaces(db: Session, organization_id: UUID) -> int:
    return (
        db.query(Workspace)
        .filter(Workspace.organization_id == organization_id)
        .count()
    )


def get_quota_usage(db: Session, organization_id: UUID) -> OssQuotaUsageSnapshot:
    return OssQuotaUsageSnapshot(
        user_metrics=count_user_metrics(db, organization_id),
        agents=count_agents(db, organization_id),
        org_members=count_org_members(db, organization_id),
        workspaces=count_workspaces(db, organization_id),
    )


def get_quotas_snapshot(organization_id: UUID) -> OssQuotasSnapshot:
    if has_enterprise_entitlement(organization_id):
        return OssQuotasSnapshot(
            max_user_metrics=None,
            max_agents=None,
            max_org_members=None,
            max_workspaces=None,
        )
    return OssQuotasSnapshot(
        max_user_metrics=OSS_MAX_USER_METRICS,
        max_agents=OSS_MAX_AGENTS,
        max_org_members=OSS_MAX_ORG_MEMBERS,
        max_workspaces=OSS_MAX_WORKSPACES,
    )


def _count_for_resource(
    db: Session,
    organization_id: UUID,
    resource: OssQuotaResource,
) -> int:
    if resource == "metrics":
        return count_user_metrics(db, organization_id)
    if resource == "agents":
        return count_agents(db, organization_id)
    if resource == "org_members":
        return count_org_members(db, organization_id)
    if resource == "workspaces":
        return count_workspaces(db, organization_id)
    raise ValueError(f"Unknown OSS quota resource: {resource}")


def enforce_oss_quota(
    db: Session,
    organization_id: UUID,
    resource: OssQuotaResource,
    *,
    additional: int = 1,
) -> None:
    """Raise HTTP 403 when an OSS org would exceed a quantity cap."""
    if has_enterprise_entitlement(organization_id):
        return

    limit = _RESOURCE_LIMITS[resource]
    current = _count_for_resource(db, organization_id, resource)
    if current + additional > limit:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "oss_quota_exceeded",
                "resource": resource,
                "limit": limit,
                "current": current,
                "message": (
                    f"{_RESOURCE_MESSAGES[resource]} "
                    "Set EFFICIENTAI_LICENSE to unlock unlimited capacity. "
                    "Contact sales@efficientai.com for an enterprise license key."
                ),
            },
        )
