"""Metrics routes."""

import json
import re
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from uuid import UUID
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from loguru import logger

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key, get_workspace_id
from app.models.database import Metric, MetricCategory, MetricType, MetricTrigger, ModelProvider
from app.models.schemas import (
    MetricCreate,
    MetricCreateWithChildren,
    MetricChildDraft,
    MetricUpdate,
    MetricResponse,
    PromoteDiscoveredChildRequest,
    PromoteDiscoveredMetricRequest,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# ---------------------------------------------------------------------------
# Hierarchy helpers
#
# Metrics support a 2-level hierarchy:
#   - A parent (selection_mode set, parent_metric_id NULL) acts as a
#     category container; its description gives the LLM context for the
#     children.
#   - Each child (parent_metric_id set, selection_mode NULL) is a
#     boolean sub-metric label.
# Both levels are real ``Metric`` rows so they can be filtered,
# aggregated, and CSV-exported independently.
# ---------------------------------------------------------------------------


_VALID_SELECTION_MODES = {"single_choice", "multi_label"}


def _validate_hierarchy_fields(
    organization_id: UUID,
    db: Session,
    *,
    parent_metric_id: Optional[UUID],
    selection_mode: Optional[str],
    metric_type: Optional[Any] = None,
    allow_discovery: Optional[bool] = None,
) -> None:
    """Enforce the invariants documented on ``Metric``.

    Raises ``HTTPException`` (400) when the caller mixes parent and
    child semantics on the same row, references a non-existent parent,
    tries to nest a child under another child (max depth = 2), or sets
    ``allow_discovery`` on a non-parent (children / standalone metrics).
    """

    if selection_mode and parent_metric_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "A metric cannot be a parent (selection_mode) and a child "
                "(parent_metric_id) at the same time."
            ),
        )

    if selection_mode and selection_mode not in _VALID_SELECTION_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid selection_mode '{selection_mode}'. Allowed values: "
                f"{', '.join(sorted(_VALID_SELECTION_MODES))}."
            ),
        )

    # ``allow_discovery`` is meaningful only on parent metrics (any
    # selection mode). On children / standalone metrics it has nothing
    # to act on — the LLM-judge would not know what taxonomy to extend.
    # For single_choice parents the flag is supplemental: discovered
    # labels are emitted alongside the predefined children but do NOT
    # break the exactly-one-true invariant (the chosen child is still
    # picked from the predefined set unless promoted later).
    if allow_discovery:
        if parent_metric_id is not None or not selection_mode:
            raise HTTPException(
                status_code=400,
                detail=(
                    "allow_discovery can only be enabled on a parent "
                    "category metric (one with selection_mode set)."
                ),
            )

    if parent_metric_id is None:
        return

    parent = (
        db.query(Metric)
        .filter(
            Metric.id == parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=400,
            detail=(
                f"parent_metric_id {parent_metric_id} does not exist in this "
                "organization."
            ),
        )
    if parent.parent_metric_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot nest a sub-metric under another sub-metric — metric "
                "hierarchies are at most 2 levels deep."
            ),
        )
    if not parent.selection_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Metric {parent_metric_id} is not a parent (no selection_mode "
                "set) and cannot own children."
            ),
        )


def _serialize_metric_tree(metric: Metric) -> Dict[str, Any]:
    """Convert a Metric ORM row into a dict shaped for ``MetricResponse``.

    Children are inlined when this row is a parent. We hand-build the
    dict (instead of relying on ``from_attributes``) so the children
    list is always populated in one pass without triggering N+1
    relationship loads later.
    """
    children_payload: List[Dict[str, Any]] = []
    if metric.selection_mode:
        for child in sorted(
            metric.children or [], key=lambda c: c.created_at or c.id
        ):
            children_payload.append(_serialize_metric_tree(child))

    return {
        "id": metric.id,
        "organization_id": metric.organization_id,
        "workspace_id": metric.workspace_id,
        # Convenience field for the UI: NULL workspace_id == org-shared.
        # Computed here rather than stored on the row so the source of
        # truth stays the column itself.
        "scope": (
            "organization" if metric.workspace_id is None else "workspace"
        ),
        "name": metric.name,
        "description": metric.description,
        "example": getattr(metric, "example", None),
        "metric_type": metric.metric_type,
        "metric_category": getattr(metric, "metric_category", "quality") or "quality",
        "trigger": metric.trigger,
        "enabled": metric.enabled,
        "is_default": metric.is_default,
        "metric_origin": metric.metric_origin,
        "supported_surfaces": metric.supported_surfaces or [],
        "enabled_surfaces": metric.enabled_surfaces or [],
        "custom_data_type": metric.custom_data_type,
        "custom_config": metric.custom_config,
        "tags": metric.tags,
        "capture_rationale": bool(metric.capture_rationale),
        "parent_metric_id": metric.parent_metric_id,
        "selection_mode": metric.selection_mode,
        "allow_discovery": bool(getattr(metric, "allow_discovery", False)),
        "compare_transcripts": bool(
            getattr(metric, "compare_transcripts", False)
        ),
        "children": children_payload,
        "created_at": metric.created_at,
        "updated_at": metric.updated_at,
        "created_by": metric.created_by,
    }


@router.post("", response_model=MetricResponse, status_code=201)
def create_metric(
    metric_data: MetricCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Create a new metric.

    Supports flat metrics, parent "category" metrics (set
    ``selection_mode``), and child sub-metrics (set
    ``parent_metric_id``). Name uniqueness is scoped to
    ``(organization_id, workspace_id, parent_metric_id)`` so the same
    label can exist in multiple workspaces (and under multiple parents).

    Scope:
      * ``scope="workspace"`` (default) stamps the metric with the
        active ``X-Workspace-Id`` (existing behavior).
      * ``scope="organization"`` stamps ``workspace_id=NULL`` so the
        metric appears in every workspace of the caller's org.

    Children always inherit their parent's scope (workspace UUID or
    NULL) - we override the request's workspace + scope when
    ``parent_metric_id`` is set so a stale UI can't accidentally split
    a tree across workspaces or scopes.
    """
    _validate_hierarchy_fields(
        organization_id,
        db,
        parent_metric_id=metric_data.parent_metric_id,
        selection_mode=metric_data.selection_mode,
        metric_type=metric_data.metric_type,
        allow_discovery=metric_data.allow_discovery,
    )

    # Resolve the effective workspace for this row:
    #   * Child:        inherit parent.workspace_id (possibly NULL).
    #   * Org-shared:   NULL.
    #   * Workspace:    active workspace from X-Workspace-Id.
    if metric_data.parent_metric_id is not None:
        parent_row = (
            db.query(Metric)
            .filter(
                Metric.id == metric_data.parent_metric_id,
                Metric.organization_id == organization_id,
            )
            .first()
        )
        if parent_row is None:
            raise HTTPException(
                status_code=400, detail="Parent metric not found."
            )
        effective_workspace_id: Optional[UUID] = parent_row.workspace_id
    elif metric_data.scope == "organization":
        effective_workspace_id = None
    else:
        effective_workspace_id = workspace_id

    # Duplicate-name check must respect BOTH the workspace AND the parent.
    # ``workspace_id IS NULL`` is a separate slot from any specific
    # workspace (matching the partial unique indexes added in
    # 041_org_shared_metrics.py).
    workspace_filter = (
        Metric.workspace_id.is_(None)
        if effective_workspace_id is None
        else Metric.workspace_id == effective_workspace_id
    )
    parent_filter = (
        Metric.parent_metric_id.is_(None)
        if metric_data.parent_metric_id is None
        else Metric.parent_metric_id == metric_data.parent_metric_id
    )
    existing = (
        db.query(Metric)
        .filter(
            Metric.name == metric_data.name,
            Metric.organization_id == organization_id,
            workspace_filter,
            parent_filter,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A metric with this name already exists",
        )

    enabled_surfaces = (
        metric_data.enabled_surfaces
        if metric_data.enabled_surfaces is not None
        else ((metric_data.supported_surfaces or ["agent"]) if metric_data.enabled else [])
    )

    # Children are always boolean — they are the "yes/no" leaves of a
    # parent category. Force the type server-side so a stale UI payload
    # can't sneak in a rating/number child that the LLM grouping logic
    # wouldn't know how to handle.
    effective_metric_type = metric_data.metric_type
    if metric_data.parent_metric_id is not None:
        effective_metric_type = MetricType.BOOLEAN

    metric = Metric(
        organization_id=organization_id,
        workspace_id=effective_workspace_id,
        name=metric_data.name,
        description=metric_data.description,
        example=metric_data.example,
        metric_type=effective_metric_type,
        metric_category=metric_data.metric_category,
        trigger=metric_data.trigger,
        enabled=len(enabled_surfaces) > 0,
        is_default=False,
        metric_origin=metric_data.metric_origin or "custom",
        supported_surfaces=metric_data.supported_surfaces or ["agent"],
        enabled_surfaces=enabled_surfaces,
        custom_data_type=metric_data.custom_data_type,
        custom_config=metric_data.custom_config,
        tags=metric_data.tags,
        capture_rationale=bool(metric_data.capture_rationale),
        parent_metric_id=metric_data.parent_metric_id,
        selection_mode=metric_data.selection_mode,
        allow_discovery=bool(metric_data.allow_discovery),
        compare_transcripts=bool(metric_data.compare_transcripts),
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)

    return _serialize_metric_tree(metric)


@router.post(
    "/with-children",
    response_model=MetricResponse,
    status_code=201,
    operation_id="createMetricWithChildren",
)
def create_metric_with_children(
    payload: MetricCreateWithChildren,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Atomically create a parent category metric plus its children.

    The parent gets ``metric_type=text`` (it's a category label, not a
    score) and ``selection_mode`` from the payload. Every child is
    forced to ``boolean`` so the LLM-evaluation path treats them as
    yes/no labels. Both the parent and all children are stamped with
    the same scope: either the active workspace (``scope="workspace"``,
    default) or ``workspace_id=NULL`` (``scope="organization"``, the
    org-shared shape).
    """
    if payload.selection_mode not in _VALID_SELECTION_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid selection_mode '{payload.selection_mode}'. "
                f"Allowed: {', '.join(sorted(_VALID_SELECTION_MODES))}."
            ),
        )

    # Org-shared categories live with ``workspace_id=NULL`` so every
    # workspace in the org sees the same category + children.
    effective_workspace_id: Optional[UUID] = (
        None if payload.scope == "organization" else workspace_id
    )
    parent_workspace_filter = (
        Metric.workspace_id.is_(None)
        if effective_workspace_id is None
        else Metric.workspace_id == effective_workspace_id
    )
    parent_existing = (
        db.query(Metric)
        .filter(
            Metric.name == payload.name,
            Metric.organization_id == organization_id,
            parent_workspace_filter,
            Metric.parent_metric_id.is_(None),
        )
        .first()
    )
    if parent_existing:
        raise HTTPException(
            status_code=400,
            detail=f"A top-level metric named '{payload.name}' already exists.",
        )

    # Detect duplicate child names within the same request before any
    # writes — the DB has no compound uniqueness constraint, so we
    # enforce it in code.
    child_names_seen: set[str] = set()
    for child in payload.children:
        key = (child.name or "").strip().lower()
        if not key:
            raise HTTPException(
                status_code=400, detail="Child sub-metric name is required."
            )
        if key in child_names_seen:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Duplicate child sub-metric name '{child.name}' in "
                    "request."
                ),
            )
        child_names_seen.add(key)

    enabled_surfaces = (
        payload.enabled_surfaces
        if payload.enabled_surfaces is not None
        else (payload.supported_surfaces or ["agent"]) if payload.enabled else []
    )

    # ``allow_discovery`` requires a parent (selection_mode set).
    # Both single_choice and multi_label parents are valid hosts; the
    # prompt builder + mapper handle the per-mode semantics.
    if payload.allow_discovery and not payload.selection_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "allow_discovery can only be enabled on a parent "
                "category metric (one with selection_mode set)."
            ),
        )

    parent = Metric(
        organization_id=organization_id,
        workspace_id=effective_workspace_id,
        name=payload.name,
        description=payload.description,
        # The parent itself stores no numeric value — its "result" is the
        # set of true children. Treat it as text so the rest of the
        # stack (aggregation, CSV export, etc.) renders the chosen child
        # name as the parent's "value".
        metric_type=MetricType.TEXT,
        metric_category=payload.metric_category,
        trigger=MetricTrigger.ALWAYS,
        enabled=len(enabled_surfaces) > 0,
        is_default=False,
        metric_origin="custom",
        supported_surfaces=payload.supported_surfaces or ["agent"],
        enabled_surfaces=enabled_surfaces,
        tags=payload.tags,
        # Hierarchical mode now captures rationale at the PARENT level
        # (the LLM emits one rationale per category, never per child),
        # so honour the user's toggle here and force children below to
        # capture_rationale=False.
        capture_rationale=bool(payload.capture_rationale),
        selection_mode=payload.selection_mode,
        allow_discovery=bool(payload.allow_discovery),
    )
    db.add(parent)
    db.flush()

    for child_draft in payload.children:
        child = Metric(
            organization_id=organization_id,
            # Children inherit the parent's scope (workspace UUID or
            # NULL for org-shared) so the whole category subtree stays
            # in one place.
            workspace_id=effective_workspace_id,
            name=child_draft.name,
            description=child_draft.description,
            example=child_draft.example,
            metric_type=MetricType.BOOLEAN,
            metric_category=payload.metric_category,
            trigger=MetricTrigger.ALWAYS,
            enabled=bool(child_draft.enabled) and len(enabled_surfaces) > 0,
            is_default=False,
            metric_origin="custom",
            supported_surfaces=payload.supported_surfaces or ["agent"],
            enabled_surfaces=(
                enabled_surfaces if child_draft.enabled else []
            ),
            custom_data_type="boolean",
            custom_config={},
            tags=child_draft.tags,
            # Children in hierarchical mode never carry their own
            # rationale — the parent owns the single rationale string
            # for the whole group. Force false regardless of payload so
            # legacy clients can't accidentally enable per-child
            # rationales that the worker would then ignore.
            capture_rationale=False,
            parent_metric_id=parent.id,
        )
        db.add(child)

    db.commit()
    db.refresh(parent)
    return _serialize_metric_tree(parent)


@router.post(
    "/{metric_id}/children",
    response_model=MetricResponse,
    status_code=201,
    operation_id="addMetricChild",
)
def add_metric_child(
    metric_id: UUID,
    child_draft: MetricChildDraft,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Append a new child sub-metric under an existing parent."""

    parent = (
        db.query(Metric)
        .filter(
            Metric.id == metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent metric not found")
    if not parent.selection_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot add a child to a metric that has no selection_mode "
                "(it is not a parent / category metric)."
            ),
        )
    if parent.parent_metric_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot nest a sub-metric under another sub-metric.",
        )

    existing = (
        db.query(Metric)
        .filter(
            Metric.name == child_draft.name,
            Metric.organization_id == organization_id,
            Metric.parent_metric_id == parent.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A child named '{child_draft.name}' already exists under "
                "this parent."
            ),
        )

    enabled_surfaces = parent.enabled_surfaces or []
    child = Metric(
        organization_id=organization_id,
        # Children always inherit the parent's workspace - this keeps
        # the tree atomic across a single workspace and avoids the
        # surprise of a child living in a different workspace than its
        # parent (which would otherwise be possible if the caller is
        # in a different active workspace at add-child time).
        workspace_id=parent.workspace_id,
        name=child_draft.name,
        description=child_draft.description,
        example=child_draft.example,
        metric_type=MetricType.BOOLEAN,
        trigger=MetricTrigger.ALWAYS,
        enabled=bool(child_draft.enabled) and len(enabled_surfaces) > 0,
        is_default=False,
        metric_origin="custom",
        supported_surfaces=parent.supported_surfaces or ["agent"],
        enabled_surfaces=enabled_surfaces if child_draft.enabled else [],
        custom_data_type="boolean",
        custom_config={},
        tags=child_draft.tags,
        # Children in hierarchical mode never carry their own
        # rationale — the parent owns the single rationale string
        # for the whole group.
        capture_rationale=False,
        parent_metric_id=parent.id,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    # Returning the freshly-created child (rather than the parent
    # subtree) gives the caller direct access to the new id +
    # parent_metric_id, which is what API consumers — and the
    # endpoint contract test — expect from a 201 on a creation
    # endpoint. Use the bare serializer so we don't materialize
    # phantom ``children`` on what is itself a leaf.
    return _serialize_metric_tree(child)


def _slug_label(value: Optional[str]) -> str:
    """Slug helper local to this module (mirrors the worker convention)."""
    if value is None:
        return ""
    return "_".join(str(value).strip().lower().split())


@router.post(
    "/{metric_id}/children/from-discovered",
    response_model=MetricResponse,
    status_code=201,
    operation_id="promoteDiscoveredChild",
)
def promote_discovered_child(
    metric_id: UUID,
    body: PromoteDiscoveredChildRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Promote an LLM-discovered candidate label into a real child metric.

    Mirrors ``add_metric_child`` but:
      * Works on any parent (single_choice OR multi_label) that has
        ``allow_discovery=true``.
      * The new child's name is normalized so that ``slug(name)`` equals
        the supplied ``key``. This is critical — without it, the
        already-scored rows' ``sequence`` arrays would not resolve
        against the promoted child once the candidate disappears from
        ``discovered_labels``.
    """

    parent = (
        db.query(Metric)
        .filter(
            Metric.id == metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent metric not found")
    if parent.parent_metric_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot promote a discovered label on a child metric.",
        )
    if not (parent.selection_mode or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Discovered-label promotion is only supported on parent "
                "category metrics (selection_mode set)."
            ),
        )
    if not bool(getattr(parent, "allow_discovery", False)):
        raise HTTPException(
            status_code=400,
            detail=(
                "This parent metric does not have allow_discovery "
                "enabled; nothing to promote."
            ),
        )

    key = _slug_label(body.key)
    name_slug = _slug_label(body.name)
    if not key:
        raise HTTPException(
            status_code=400, detail="Discovered key must be a non-empty slug."
        )
    if name_slug != key:
        # Either the caller mis-typed the name or they intentionally
        # picked a friendlier display name. The frontend should send a
        # name whose slug matches the key, but to keep the contract
        # explicit we reject the mismatch rather than silently mutate
        # the user's typed name.
        raise HTTPException(
            status_code=400,
            detail=(
                "name must slugify to the supplied key so already-scored "
                f"rows' sequence arrays keep resolving. Got key='{key}' "
                f"but slug(name)='{name_slug}'."
            ),
        )

    existing = (
        db.query(Metric)
        .filter(
            Metric.name == body.name,
            Metric.organization_id == organization_id,
            Metric.parent_metric_id == parent.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A child named '{body.name}' already exists under this "
                "parent."
            ),
        )

    enabled_surfaces = parent.enabled_surfaces or []
    child = Metric(
        organization_id=organization_id,
        # Children always live in the parent's workspace; users who
        # have switched workspaces in the UI between viewing the
        # discovered-labels panel and clicking Promote still get a
        # consistent tree.
        workspace_id=parent.workspace_id,
        name=body.name,
        description=body.description,
        metric_type=MetricType.BOOLEAN,
        trigger=MetricTrigger.ALWAYS,
        enabled=len(enabled_surfaces) > 0,
        is_default=False,
        metric_origin="custom",
        supported_surfaces=parent.supported_surfaces or ["agent"],
        enabled_surfaces=enabled_surfaces,
        custom_data_type="boolean",
        custom_config={},
        tags=None,
        # Default True (matching the request schema) so future rows
        # that hit the new child keep producing rationales — the
        # discovered candidate was itself proposed *with* a rationale,
        # and users almost always want that signal preserved on the
        # promoted child. Callers that want the v2 hierarchical
        # behavior (parent-only rationale) pass ``capture_rationale=
        # false`` explicitly.
        capture_rationale=bool(body.capture_rationale),
        parent_metric_id=parent.id,
    )
    db.add(child)
    db.commit()
    db.refresh(parent)
    return _serialize_metric_tree(parent)


# Map the ``DiscoveredMetricSuggestedType`` literal to the canonical
# ``MetricType`` + ``custom_data_type``/``selection_mode`` shape we
# persist on a real :class:`Metric` row. ``category`` promotes to a
# ``multi_label`` parent with no children (the user adds children
# afterwards via the existing Metrics page).
def _resolve_discovered_metric_type(
    requested: str,
) -> tuple[MetricType, Optional[str], Optional[str]]:
    requested = (requested or "").strip().lower()
    if requested == "rating":
        return MetricType.RATING, None, None
    if requested == "category":
        # Category parents store no numeric value; downstream code
        # renders the chosen child name (or list) as the parent's
        # "value", matching ``MetricCreateWithChildren`` semantics
        # above.
        return MetricType.TEXT, None, "multi_label"
    # Default: boolean.
    return MetricType.BOOLEAN, "boolean", None


@router.post(
    "/from-discovered",
    response_model=MetricResponse,
    status_code=201,
    operation_id="promoteDiscoveredMetric",
)
def promote_discovered_metric(
    body: PromoteDiscoveredMetricRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Promote an LLM-discovered top-level metric into a real Metric row.

    Parallel to :func:`promote_discovered_child` but creates a
    standalone metric (``parent_metric_id=None``) instead of a child.
    The new metric's name is normalized so ``slug(name) == key`` —
    this keeps any already-scored rows that referenced the candidate
    under the promoted slug resolvable without a backfill, and
    prevents duplicate promotions from sneaking in under slightly
    different casing.

    ``metric_type`` selects how future evaluation runs will score the
    new metric: ``boolean`` / ``rating`` are scored standalone;
    ``category`` creates a ``multi_label`` parent with no children
    that the user can populate via the Metrics page.
    """

    key = _slug_label(body.key)
    name_slug = _slug_label(body.name)
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Discovered key must be a non-empty slug.",
        )
    if name_slug != key:
        raise HTTPException(
            status_code=400,
            detail=(
                "name must slugify to the supplied key so already-scored "
                f"rows that referenced the candidate keep resolving. "
                f"Got key='{key}' but slug(name)='{name_slug}'."
            ),
        )

    existing = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.workspace_id == workspace_id,
            Metric.parent_metric_id.is_(None),
            Metric.name == body.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A top-level metric named '{body.name}' already exists "
                "in this workspace."
            ),
        )

    metric_type, custom_data_type, selection_mode = (
        _resolve_discovered_metric_type(body.metric_type)
    )

    supported_surfaces = ["agent"]
    enabled_surfaces = ["agent"]

    metric = Metric(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=body.name,
        description=body.description,
        metric_type=metric_type,
        trigger=MetricTrigger.ALWAYS,
        # Newly-promoted discoveries are enabled by default; the user
        # can disable from the Metrics page if they decide they don't
        # want it scored on future runs.
        enabled=True,
        is_default=False,
        metric_origin="custom",
        supported_surfaces=supported_surfaces,
        enabled_surfaces=enabled_surfaces,
        custom_data_type=custom_data_type,
        custom_config=body.custom_config or None,
        tags=None,
        # Standalone metric — rationale is per-metric (default true so
        # the LLM keeps producing rationales for promoted candidates,
        # matching the discovered-labels promote default).
        capture_rationale=bool(body.capture_rationale),
        parent_metric_id=None,
        selection_mode=selection_mode,
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return _serialize_metric_tree(metric)


@router.get("", response_model=List[MetricResponse])
def list_metrics(
    surface: Optional[str] = None,
    include_children: bool = Query(
        True,
        description=(
            "When true (default), children are nested under their parent "
            "and not returned as top-level rows. When false, the response "
            "is a flat list of every metric (parents + standalone + "
            "orphaned children)."
        ),
    ),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """List metrics with optional nesting for the parent/child hierarchy.

    Returns the union of:
      * Metrics scoped to the active workspace (``workspace_id == ws``).
      * Metrics shared at the org level (``workspace_id IS NULL``).

    This is what makes org-shared metrics appear inside every workspace
    of the org without the user having to recreate them. Switching
    workspace in the UI still narrows the workspace-scoped half; the
    org-shared half is identical across workspaces.
    """
    query = db.query(Metric).filter(
        Metric.organization_id == organization_id,
        or_(
            Metric.workspace_id == workspace_id,
            Metric.workspace_id.is_(None),
        ),
        ~Metric.name.in_(REMOVED_DEFAULT_METRICS),
        ~and_(
            Metric.is_default == True,
            Metric.metric_category == MetricCategory.USER_INSIGHT.value,
            Metric.metric_origin == "default",
        ),
    )
    metrics = (
        query.order_by(Metric.is_default.desc(), Metric.created_at.desc()).all()
    )
    if surface:
        normalized_surface = surface.strip().lower()
        metrics = [
            m for m in metrics
            if normalized_surface in (m.supported_surfaces or [])
        ]

    if not include_children:
        return [_serialize_metric_tree(m) for m in metrics]

    # Top-level rows = anything without a parent, OR a child whose parent
    # is not visible at this surface (so users still see "orphaned"
    # children rather than losing them silently).
    visible_ids = {m.id for m in metrics}
    top_level = [
        m
        for m in metrics
        if m.parent_metric_id is None or m.parent_metric_id not in visible_ids
    ]
    return [_serialize_metric_tree(m) for m in top_level]


@router.get("/{metric_id}", response_model=MetricResponse)
def get_metric(
    metric_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific metric, with children inlined for parents."""
    metric = db.query(Metric).filter(
        and_(
            Metric.id == metric_id,
            Metric.organization_id == organization_id
        )
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    return _serialize_metric_tree(metric)


@router.put("/{metric_id}", response_model=MetricResponse)
def update_metric(
    metric_id: UUID,
    metric_data: MetricUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update a metric."""
    metric = db.query(Metric).filter(
        and_(
            Metric.id == metric_id,
            Metric.organization_id == organization_id
        )
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Don't allow updating default metrics' core properties
    if metric.is_default:
        if metric_data.name is not None and metric_data.name != metric.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot rename default metrics"
            )
        if metric_data.metric_type is not None and metric_data.metric_type != metric.metric_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change metric type of default metrics"
            )

    # Update fields if provided
    if metric_data.name is not None:
        # Name uniqueness is scoped to the same parent: e.g. two parents
        # may each have a child named "happy" without colliding.
        existing = (
            db.query(Metric)
            .filter(
                Metric.name == metric_data.name,
                Metric.organization_id == organization_id,
                Metric.id != metric_id,
                Metric.parent_metric_id.is_(metric.parent_metric_id)
                if metric.parent_metric_id is None
                else Metric.parent_metric_id == metric.parent_metric_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A metric with this name already exists"
            )
        metric.name = metric_data.name

    if metric_data.description is not None:
        metric.description = metric_data.description

    if metric_data.example is not None:
        # An empty string clears the stored example; ``None`` (the
        # default) means "leave unchanged" so callers that don't know
        # about the field can keep PATCHing without nuking it.
        metric.example = metric_data.example or None

    if metric_data.metric_type is not None:
        # Children stay boolean — refuse a type change request.
        if metric.parent_metric_id is not None and metric_data.metric_type != MetricType.BOOLEAN:
            raise HTTPException(
                status_code=400,
                detail="Child sub-metrics must remain boolean.",
            )
        metric.metric_type = metric_data.metric_type

    if metric_data.trigger is not None:
        metric.trigger = metric_data.trigger

    if metric_data.enabled is not None:
        metric.enabled = metric_data.enabled
        if metric_data.enabled and not metric.enabled_surfaces:
            metric.enabled_surfaces = metric.supported_surfaces or ["agent"]
        elif not metric_data.enabled:
            metric.enabled_surfaces = []

    if metric_data.metric_origin is not None:
        metric.metric_origin = metric_data.metric_origin

    if metric_data.supported_surfaces is not None:
        metric.supported_surfaces = metric_data.supported_surfaces
        if metric.enabled and not metric_data.enabled_surfaces:
            metric.enabled_surfaces = metric_data.supported_surfaces

    if metric_data.enabled_surfaces is not None:
        metric.enabled_surfaces = metric_data.enabled_surfaces
        metric.enabled = len(metric_data.enabled_surfaces) > 0

    if metric_data.custom_data_type is not None:
        metric.custom_data_type = metric_data.custom_data_type

    if metric_data.custom_config is not None:
        metric.custom_config = metric_data.custom_config

    if metric_data.tags is not None:
        metric.tags = metric_data.tags

    if metric_data.metric_category is not None:
        metric.metric_category = metric_data.metric_category

    if metric_data.capture_rationale is not None:
        # Child sub-metrics never carry their own rationale — the parent
        # owns the single rationale string for the whole categorization
        # group. Silently coerce to False so legacy clients can't
        # re-introduce per-child rationales.
        if metric.parent_metric_id is not None:
            metric.capture_rationale = False
        else:
            metric.capture_rationale = bool(metric_data.capture_rationale)

    if metric_data.selection_mode is not None:
        # Only parent rows can flip selection_mode. Children + standalone
        # metrics with no children are rejected so the worker grouping
        # logic doesn't have to second-guess what mode a row is in.
        if metric.parent_metric_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot set selection_mode on a child sub-metric.",
            )
        if metric_data.selection_mode not in _VALID_SELECTION_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid selection_mode '{metric_data.selection_mode}'. "
                    f"Allowed: {', '.join(sorted(_VALID_SELECTION_MODES))}."
                ),
            )
        metric.selection_mode = metric_data.selection_mode

    if metric_data.allow_discovery is not None:
        # ``allow_discovery`` is only meaningful on parent rows. Use
        # the value already on the row (which may have been just set
        # in this same PATCH) to enforce the parent invariant.
        effective_mode = metric.selection_mode
        if metric.parent_metric_id is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "allow_discovery cannot be set on a child sub-metric."
                ),
            )
        if bool(metric_data.allow_discovery) and not effective_mode:
            raise HTTPException(
                status_code=400,
                detail=(
                    "allow_discovery can only be enabled on a parent "
                    "category metric (one with selection_mode set)."
                ),
            )
        metric.allow_discovery = bool(metric_data.allow_discovery)

    if metric_data.compare_transcripts is not None:
        # Cross-state validation: a Metric can be a transcript-compare
        # judge only if it's standalone (not a child sub-metric and not
        # a parent category). ``compare_transcripts=False`` clears the
        # flag unconditionally (used to "downgrade" a comparison metric
        # back to a regular transcript judge).
        if bool(metric_data.compare_transcripts):
            if metric.parent_metric_id is not None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "compare_transcripts cannot be enabled on a "
                        "child sub-metric. Promote it to a standalone "
                        "metric first."
                    ),
                )
            # Read the freshly-patched selection_mode value so users
            # can clear+set in one PATCH.
            if metric.selection_mode is not None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "compare_transcripts cannot be enabled on a "
                        "parent category metric. Convert it to a "
                        "standalone metric first."
                    ),
                )
        metric.compare_transcripts = bool(metric_data.compare_transcripts)

    db.commit()
    db.refresh(metric)

    return _serialize_metric_tree(metric)


# Deprecated default metrics that can be deleted
DEPRECATED_DEFAULT_METRICS = {"Response Time", "Customer Satisfaction", "Clarity and Empathy"}
# Removed default metrics should no longer be listed/seeded/evaluated.
REMOVED_DEFAULT_METRICS = {"Clarity and Empathy", "Problem Resolution"}


@router.delete("/{metric_id}", status_code=204)
def delete_metric(
    metric_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a metric."""
    metric = db.query(Metric).filter(
        and_(
            Metric.id == metric_id,
            Metric.organization_id == organization_id
        )
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Allow deletion of deprecated default metrics
    if metric.is_default and metric.name not in DEPRECATED_DEFAULT_METRICS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete default metrics"
        )

    # Explicitly remove children before the parent. The FK declares
    # ``ON DELETE CASCADE`` so PostgreSQL would handle this for us,
    # but SQLite (used by the in-memory test harness) doesn't enforce
    # FK constraints by default and the SQLAlchemy relationship
    # doesn't carry a cascade rule. Going through the ORM keeps the
    # session's identity map consistent on either engine.
    if metric.parent_metric_id is None:
        for child in list(metric.children or []):
            db.delete(child)

    db.delete(metric)
    db.commit()

    return None


@router.post("/seed-defaults", response_model=List[MetricResponse], status_code=201)
def seed_default_metrics(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Seed default metrics for an organization (in the active workspace).

    Default metrics live in the workspace the caller is currently in;
    this matches the rest of the metrics surface and lets a user seed
    the same defaults independently per workspace if they want to.
    """
    default_metrics = [
        # =========================================================================
        # LLM-Evaluated Metrics (Subjective assessments from conversation text)
        # =========================================================================
        {
            "name": "Follow Instructions",
            "description": "Measures how well the agent follows instructions and guidelines",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["agent", "voice_playground"],
            "enabled_surfaces": ["agent", "voice_playground"],
        },
        {
            "name": "Professionalism",
            "description": "Assesses the professional tone and behavior throughout the conversation",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["agent"],
            "enabled_surfaces": ["agent"],
        },
        # =========================================================================
        # Acoustic Metrics (Parselmouth - traditional voice analysis)
        # =========================================================================
        {
            "name": "Pitch Variance",
            "description": "Measures F0 (fundamental frequency) variation in Hz - indicates prosodic expressiveness. Higher values suggest more expressive speech.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Jitter",
            "description": "Cycle-to-cycle pitch period variation as percentage - indicates vocal stability. Lower values (< 1%) indicate stable voice.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": False,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": [],
        },
        {
            "name": "Shimmer",
            "description": "Cycle-to-cycle amplitude variation as percentage - indicates voice quality. Lower values (< 3%) indicate consistent voice.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": False,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": [],
        },
        {
            "name": "HNR",
            "description": "Harmonics-to-Noise Ratio in dB - indicates voice clarity. Higher values (> 20 dB) indicate cleaner voice with less breathiness.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": False,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": [],
        },
        # =========================================================================
        # AI Voice Metrics (ML models - human-likeness, emotion, consistency)
        # =========================================================================
        {
            "name": "MOS Score",
            "description": "Mean Opinion Score (1.0-5.0) - predicts human perception of audio quality. 1-2: Poor/robotic, 3: Telephone quality, 4-5: Studio/high fidelity.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Emotion Category",
            "description": "Categorical emotion detected in the voice (angry, happy, sad, neutral, fearful, disgusted, surprised).",
            "metric_type": MetricType.RATING,  # Stored as text category
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Emotion Confidence",
            "description": "Confidence score (0.0-1.0) for the detected emotion category.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Valence",
            "description": "Emotional positivity/negativity (-1.0 to +1.0). Negative = sad/angry, Positive = happy/excited.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Arousal",
            "description": "Emotional intensity/energy (0.0-1.0). Low = calm/sleepy, High = excited/energetic.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Speaker Consistency",
            "description": "Voice identity stability (0.0-1.0). Compares start vs end of call. >0.8 = same voice, <0.5 = voice change detected (possible glitch).",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Prosody Score",
            "description": "Expressiveness/Drama score (0.0-1.0). Low = monotone/flat, High = expressive/dynamic storyteller.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
    ]

    # Names of default voice metrics that must always be enabled on the
    # voice_playground surface for existing organizations. These are the
    # qualitative audio metrics computed by qualitative_voice_service that
    # the voice playground relies on; the worker honors enabled_surfaces and
    # will skip computation entirely if none are enabled.
    voice_playground_required_defaults = {
        "MOS Score", "Valence", "Arousal", "Prosody Score",
        "Emotion Category", "Emotion Confidence", "Speaker Consistency",
    }

    created_metrics = []
    for metric_data in default_metrics:
        # Per-workspace seeding: a default that already exists in this
        # workspace is left alone, but the same default in a sibling
        # workspace is created fresh. Match on
        # (organization_id, workspace_id, name).
        existing = db.query(Metric).filter(
            and_(
                Metric.name == metric_data["name"],
                Metric.organization_id == organization_id,
                Metric.workspace_id == workspace_id,
            )
        ).first()

        if not existing:
            metric = Metric(
                organization_id=organization_id,
                workspace_id=workspace_id,
                name=metric_data["name"],
                description=metric_data["description"],
                metric_type=metric_data["metric_type"],
                metric_category=metric_data.get(
                    "metric_category", MetricCategory.QUALITY.value
                ),
                trigger=metric_data["trigger"],
                enabled=metric_data["enabled"],
                is_default=True,
                metric_origin=metric_data.get("metric_origin", "default"),
                supported_surfaces=metric_data.get("supported_surfaces", ["agent"]),
                enabled_surfaces=metric_data.get("enabled_surfaces", ["agent"]),
            )
            db.add(metric)
            created_metrics.append(metric)
        else:
            # Keep default acoustic metric toggles aligned with product defaults.
            if existing.enabled != metric_data["enabled"]:
                existing.enabled = metric_data["enabled"]
            # Re-assert voice_playground surface enrollment for the four required
            # voice metrics so existing orgs pick up the new default behavior.
            if metric_data["name"] in voice_playground_required_defaults:
                supported = list(existing.supported_surfaces or [])
                if "voice_playground" not in supported:
                    supported.append("voice_playground")
                    existing.supported_surfaces = supported
                enabled_surfaces = list(existing.enabled_surfaces or [])
                if "voice_playground" not in enabled_surfaces:
                    enabled_surfaces.append("voice_playground")
                    existing.enabled_surfaces = enabled_surfaces
                    existing.enabled = True

    # Disable legacy default user-insight metrics (no longer seeded).
    legacy_user_insights = db.query(Metric).filter(
        and_(
            Metric.organization_id == organization_id,
            Metric.workspace_id == workspace_id,
            Metric.is_default == True,
            Metric.metric_category == MetricCategory.USER_INSIGHT.value,
            Metric.metric_origin == "default",
            Metric.enabled == True,
        )
    ).all()
    for metric in legacy_user_insights:
        metric.enabled = False

    # Ensure removed defaults are disabled in the active workspace
    # (a sibling workspace's data is left alone; users who want the
    # cleanup applied org-wide can run seed-defaults in each workspace).
    removed_metrics = db.query(Metric).filter(
        and_(
            Metric.organization_id == organization_id,
            Metric.workspace_id == workspace_id,
            Metric.name.in_(REMOVED_DEFAULT_METRICS),
            Metric.enabled == True,
        )
    ).all()
    for metric in removed_metrics:
        metric.enabled = False

    db.commit()
    for metric in created_metrics:
        db.refresh(metric)

    return created_metrics


# =============================================================================
# AI metric generation
# =============================================================================

class MetricGenerateExample(BaseModel):
    """One labeled example used to infer a metric definition."""
    transcript: str
    rating: Any  # number, boolean, or label (model-decided)
    notes: Optional[str] = None


class MetricGenerateRequest(BaseModel):
    """Request body for AI-generated metric suggestion."""
    mode: Literal["description", "examples"]
    surface: Literal["agent", "voice_playground", "blind_test"] = "agent"
    description: Optional[str] = Field(
        default=None,
        description="Free-form description of what the metric should measure (mode=description).",
    )
    examples: Optional[List[MetricGenerateExample]] = Field(
        default=None,
        description="Labeled examples used to infer the metric (mode=examples).",
    )
    provider: Optional[str] = None
    model: Optional[str] = None
    llm_config: Optional[Dict[str, Any]] = None


class MetricGenerateResponse(BaseModel):
    """Suggested (un-persisted) metric definition returned to the client."""
    name: str
    description: str
    metric_type: Literal["rating", "boolean", "number", "text"]
    custom_data_type: Optional[Literal["boolean", "enum", "number_range"]] = None
    custom_config: Dict[str, Any] = {}
    supported_surfaces: List[str]
    enabled_surfaces: List[str]
    suggested_tags: List[str] = []
    provider: Optional[str] = None
    model: Optional[str] = None


def _build_metric_generation_messages(req: MetricGenerateRequest) -> List[Dict[str, str]]:
    """Build the LLM prompt for generating a metric definition."""
    surfaces_block = (
        f'  - "supported_surfaces": list, must include "{req.surface}". '
        f'Other allowed values: "agent", "voice_playground", "blind_test".\n'
        f'  - "enabled_surfaces": list, default to the same as supported_surfaces.\n'
    )

    schema_block = """
You MUST respond with ONLY a JSON object (no markdown, no commentary) with this exact shape:
{
  "name": str (concise, Title Case, <= 60 chars),
  "description": str (1-3 sentences explaining what is measured and how to score it),
  "metric_type": "rating" | "boolean" | "number" | "text",
  "custom_data_type": "boolean" | "enum" | "number_range" | null,
  "custom_config": {
      // for "enum": {"options": ["...", "..."]}
      // for "number_range": {"min": <number>, "max": <number>, "step": <number>}
      // for "boolean": {}
      // for "text": {}  (no extra config; the description tells the LLM what to summarize)
  },
  "supported_surfaces": ["agent" | "voice_playground" | "blind_test", ...],
  "enabled_surfaces": ["agent" | "voice_playground" | "blind_test", ...],
  "suggested_tags": ["...", "..."]
}

Rules:
  - "metric_type" must align with "custom_data_type":
      boolean -> "boolean", enum -> "rating", number_range -> "number".
  - Use "text" ONLY when the user clearly wants a free-form sentence /
    summary / explanation / classification label as the answer (e.g. "summarize
    the call", "extract the customer's main concern", "describe what went
    wrong in one paragraph"). For text metrics, set "custom_data_type" to null
    and "custom_config" to {}.
  - Otherwise prefer a structured numeric/boolean/enum metric.
""" + surfaces_block

    system_message = (
        "You are an expert evaluation designer. You translate a user's intent into a "
        "well-formed evaluation metric definition that can be judged by an LLM-as-judge. "
        "Always respond with valid JSON only."
    )

    if req.mode == "description":
        user_message = (
            "Generate a single evaluation metric definition based on the user's request below. "
            f'The metric will be evaluated on the "{req.surface}" surface.\n\n'
            f"## User intent\n{(req.description or '').strip()}\n"
            f"{schema_block}"
        )
    else:
        examples_text = "\n".join(
            f"- Example {i + 1}:\n  transcript: {ex.transcript!r}\n  rating: {ex.rating!r}"
            + (f"\n  notes: {ex.notes!r}" if ex.notes else "")
            for i, ex in enumerate(req.examples or [])
        )
        user_message = (
            "Infer a single evaluation metric definition that explains the rating pattern "
            f'in the labeled examples below. The metric will be evaluated on the "{req.surface}" '
            "surface.\n\n"
            f"## Labeled examples\n{examples_text}\n"
            f"{schema_block}"
        )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _parse_metric_generation_response(text: str) -> Dict[str, Any]:
    """Extract a JSON object from the LLM response text."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned.replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return json.loads(match.group())
        raise


@router.post("/generate", response_model=MetricGenerateResponse)
def generate_metric(
    req: MetricGenerateRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Use an LLM to suggest a metric definition. Does NOT persist anything."""
    if req.mode == "description" and not (req.description and req.description.strip()):
        raise HTTPException(status_code=400, detail="description is required when mode='description'")
    if req.mode == "examples" and not (req.examples and len(req.examples) > 0):
        raise HTTPException(status_code=400, detail="At least one example is required when mode='examples'")

    from app.services.ai.llm_service import llm_service
    from app.services.ai.llm_resolver import get_llm_provider_and_model

    messages = _build_metric_generation_messages(req)

    provider_enum, model_str = get_llm_provider_and_model(
        organization_id, db, req.provider, req.model
    )

    try:
        llm_result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            llm_config=req.llm_config,
            task_defaults={"temperature": 0.4, "max_tokens": 800},
        )
    except Exception as e:
        logger.error(f"[Metric Generate] LLM call failed: {e}")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    try:
        parsed = _parse_metric_generation_response(llm_result.get("text", ""))
    except Exception as e:
        logger.error(f"[Metric Generate] Failed to parse LLM JSON: {e}")
        raise HTTPException(status_code=502, detail="Could not parse LLM response as JSON")

    allowed_surfaces = {"agent", "voice_playground", "blind_test"}
    supported = [s for s in (parsed.get("supported_surfaces") or []) if s in allowed_surfaces]
    if req.surface not in supported:
        supported = list({*supported, req.surface})
    enabled_surfaces = [s for s in (parsed.get("enabled_surfaces") or supported) if s in supported]
    if not enabled_surfaces:
        enabled_surfaces = list(supported)

    metric_type = (parsed.get("metric_type") or "rating").lower()
    if metric_type not in {"rating", "boolean", "number", "text"}:
        metric_type = "rating"

    custom_data_type = parsed.get("custom_data_type")
    if custom_data_type not in {"boolean", "enum", "number_range", None}:
        custom_data_type = None

    # Text metrics are unstructured by definition: no custom_data_type,
    # no extra config. Force-clear both regardless of what the LLM said so a
    # stale enum/number_range hint never sneaks through.
    if metric_type == "text":
        custom_data_type = None
        custom_config: Dict[str, Any] = {}
    else:
        if custom_data_type is None:
            custom_data_type = (
                "boolean" if metric_type == "boolean"
                else "number_range" if metric_type == "number"
                else "enum"
            )

        custom_config = parsed.get("custom_config") or {}
        if custom_data_type == "enum" and not isinstance(custom_config.get("options"), list):
            custom_config = {"options": ["Excellent", "Good", "Neutral", "Poor"]}
        if custom_data_type == "number_range":
            custom_config = {
                "min": float(custom_config.get("min", 0)),
                "max": float(custom_config.get("max", 10)),
                "step": float(custom_config.get("step", 1)),
            }
        if custom_data_type == "boolean":
            custom_config = {}

    name = (parsed.get("name") or "Custom Metric").strip()[:60]
    existing = db.query(Metric).filter(
        and_(Metric.name == name, Metric.organization_id == organization_id)
    ).first()
    if existing:
        suffix = 2
        while db.query(Metric).filter(
            and_(Metric.name == f"{name} ({suffix})", Metric.organization_id == organization_id)
        ).first():
            suffix += 1
        name = f"{name} ({suffix})"

    return MetricGenerateResponse(
        name=name,
        description=(parsed.get("description") or "").strip()[:1000],
        metric_type=metric_type,
        custom_data_type=custom_data_type,
        custom_config=custom_config,
        supported_surfaces=supported,
        enabled_surfaces=enabled_surfaces,
        suggested_tags=[str(t) for t in (parsed.get("suggested_tags") or [])][:8],
        provider=provider_enum.value,
        model=model_str,
    )


# =============================================================================
# Bulk-import: build a LIST of independent metric drafts from a labels prompt
# =============================================================================
#
# Each "Label #N" block in the pasted prompt is turned into a *separate*
# draft metric so the user can decide per metric:
#   - the metric type (boolean / rating / number / text)
#   - whether to capture an LLM rationale
#   - whether to keep / rename / delete it
# The endpoint NEVER persists anything; the frontend collects the user's
# edits and POSTs each draft to ``/metrics`` individually.

class ParsedLabel(BaseModel):
    """One label parsed out of the bulk prompt."""
    label_name: str
    definition: str = ""
    examples: str = ""


class MetricDraft(BaseModel):
    """One un-persisted metric draft built from a parsed label.

    The defaults reflect the most common shape of a parsed label
    ("did <X> happen?" → boolean, with a free-form rationale). The user
    can flip the type / rationale flag in the bulk-import modal before
    saving each draft to the metrics table.
    """
    name: str
    description: str
    metric_type: Literal["rating", "boolean", "number", "text"] = "boolean"
    custom_data_type: Optional[Literal["boolean", "enum", "number_range"]] = "boolean"
    custom_config: Dict[str, Any] = Field(default_factory=dict)
    supported_surfaces: List[str]
    enabled_surfaces: List[str]
    capture_rationale: bool = True
    suggested_tags: List[str] = Field(default_factory=list)
    # Echo the source label so the frontend can show the rubric / examples
    # alongside the editable fields without re-fetching.
    source_label: ParsedLabel


class MetricParseBulkRequest(BaseModel):
    """Request body for bulk-importing multiple metrics from a prompt.

    Optional hierarchy fields let the bulk import produce a parent
    category metric with the parsed labels as children instead of N
    independent top-level metrics.
    """
    prompt: str = Field(..., description="The pasted Label-block prompt.")
    surface: Literal["agent", "voice_playground", "blind_test"] = "agent"
    parent_name: Optional[str] = Field(
        default=None,
        max_length=120,
        description=(
            "When set, returns ONE parent draft owning every parsed label "
            "as a child. Used to build a 'category' metric in one shot."
        ),
    )
    parent_description: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Optional description used as the parent's LLM rubric.",
    )
    selection_mode: Optional[Literal["single_choice", "multi_label"]] = Field(
        default=None,
        description=(
            "Required when ``parent_name`` is set. Controls how the LLM "
            "scores children together: single_choice = exactly one true; "
            "multi_label = independent yes/no with logical consistency."
        ),
    )


class MetricParseBulkParentDraft(BaseModel):
    """Optional parent metric returned when ``parent_name`` was set."""

    name: str
    description: Optional[str] = None
    selection_mode: Literal["single_choice", "multi_label"]
    supported_surfaces: List[str]
    enabled_surfaces: List[str]


class MetricParseBulkResponse(BaseModel):
    """List of independent un-persisted metric drafts, one per label.

    ``parent`` is populated only when the request asked for a hierarchy
    (``parent_name`` set); the frontend then POSTs to
    ``/metrics/with-children`` instead of N independent ``/metrics`` calls.
    """
    metrics: List[MetricDraft]
    parent: Optional[MetricParseBulkParentDraft] = None


# A "Label #N" block looks like:
#
#   Label #1
#
#   Label Name
#   Pitch done WITH data (...)
#   Label Definition
#   The pitch window contains any numeric data tied to the seller...
#   Example (Optional)
#   Example 1 (...): ...
#
# We split on each "Label #<n>" header and then pull "Label Name",
# "Label Definition", and the "Example (Optional)" body out of each
# block independently. Section headers are matched case-insensitively
# and must each appear on their own line so prose containing the words
# can't trip the parser.
_LABEL_BLOCK_SPLIT = re.compile(r"(?im)^\s*label\s*#\s*\d+\s*$")
_LABEL_NAME_HEADER = re.compile(r"(?im)^\s*label\s+name\s*$")
_LABEL_DEFINITION_HEADER = re.compile(r"(?im)^\s*label\s+definition\s*$")
_LABEL_EXAMPLE_HEADER = re.compile(r"(?im)^\s*example(?:\s*\(optional\))?\s*$")


def _section_after(text: str, header_re: re.Pattern, *stop_res: re.Pattern) -> str:
    """Return the text between ``header_re`` and the next stop header (or EOS)."""
    match = header_re.search(text)
    if not match:
        return ""
    after = text[match.end():]
    end = len(after)
    for stop_re in stop_res:
        stop_match = stop_re.search(after)
        if stop_match and stop_match.start() < end:
            end = stop_match.start()
    return after[:end].strip()


def _parse_label_blocks(prompt: str) -> List[ParsedLabel]:
    """Deterministic regex parse of "Label #N" blocks.

    Returns labels in the order they appear. Labels with an empty name
    are skipped. Definition / examples are best-effort: missing sections
    are returned as empty strings and the caller decides whether to fall
    back to an LLM parse.
    """
    if not prompt or not prompt.strip():
        return []

    pieces = _LABEL_BLOCK_SPLIT.split(prompt)
    # The first piece (before any "Label #N" header) is preamble; ignore.
    blocks = [p for p in pieces[1:] if p.strip()]

    labels: List[ParsedLabel] = []
    for block in blocks:
        name = _section_after(
            block,
            _LABEL_NAME_HEADER,
            _LABEL_DEFINITION_HEADER,
            _LABEL_EXAMPLE_HEADER,
        )
        # Collapse whitespace: the label name should be a single line.
        name = " ".join(name.split())
        if not name:
            continue

        definition = _section_after(
            block,
            _LABEL_DEFINITION_HEADER,
            _LABEL_EXAMPLE_HEADER,
        )
        examples = _section_after(
            block,
            _LABEL_EXAMPLE_HEADER,
        )

        labels.append(
            ParsedLabel(
                label_name=name[:120],
                definition=definition[:2000],
                examples=examples[:4000],
            )
        )
    return labels


def _build_bulk_llm_prompt(prompt: str) -> List[Dict[str, str]]:
    """Build messages for an LLM fallback parse when the regex finds no labels.

    The output is a flat list of evaluation criteria; each one will be
    materialised into its OWN draft metric on the frontend, so they do
    not need to be mutually exclusive.
    """
    system = (
        "You extract a list of independent evaluation criteria (labels) "
        "from an evaluation rubric. Always respond with valid JSON only."
    )
    user = (
        "Extract every distinct evaluation criterion from the rubric below. "
        "For each one return its short label name, a 1-3 sentence definition, "
        "and any examples block (or empty string). Return JSON of shape:\n"
        '{"labels": [{"label_name": "...", "definition": "...", "examples": "..."}]}\n\n'
        "Rules:\n"
        "  - Preserve the EXACT label names as written; no summarising.\n"
        "  - Each label is independent (will become its own metric).\n"
        "  - If the rubric is unparseable, return {\"labels\": []}.\n\n"
        f"## Rubric\n{prompt.strip()}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _llm_parse_labels(
    prompt: str,
    organization_id: UUID,
    db: Session,
) -> List[ParsedLabel]:
    """Call the LLM to extract labels from a non-standard rubric format."""
    from app.services.ai.llm_service import llm_service

    messages = _build_bulk_llm_prompt(prompt)
    try:
        llm_result = llm_service.generate_response(
            messages=messages,
            llm_provider=ModelProvider.OPENAI,
            llm_model="gpt-4o",
            organization_id=organization_id,
            db=db,
            temperature=0.2,
            max_tokens=1500,
        )
    except Exception as e:
        logger.error(f"[Metric ParseBulk] LLM call failed: {e}")
        return []

    try:
        parsed = _parse_metric_generation_response(llm_result.get("text", ""))
    except Exception as e:
        logger.error(f"[Metric ParseBulk] Failed to parse LLM JSON: {e}")
        return []

    raw_labels = parsed.get("labels") if isinstance(parsed, dict) else None
    if not isinstance(raw_labels, list):
        return []

    labels: List[ParsedLabel] = []
    for item in raw_labels:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("label_name") or "").split())
        if not name:
            continue
        labels.append(
            ParsedLabel(
                label_name=name[:120],
                definition=str(item.get("definition") or "")[:2000].strip(),
                examples=str(item.get("examples") or "")[:4000].strip(),
            )
        )
    return labels


def _build_description_from_label(label: ParsedLabel) -> str:
    """Turn a parsed label block into a per-metric judging rubric.

    The result is what the LLM-judge sees as ``Metric.description`` when
    this draft is later saved. We keep the label name verbatim at the top
    so the prompt the user pasted survives intact.
    """
    parts: List[str] = []
    parts.append(
        f'Decide whether "{label.label_name}" applies to the conversation.'
    )
    if label.definition:
        parts.append(f"Definition:\n{label.definition}")
    if label.examples:
        parts.append(f"Examples:\n{label.examples}")
    description = "\n\n".join(parts)
    return description[:4000]


def _ensure_unique_metric_name(
    base_name: str,
    organization_id: UUID,
    db: Session,
    reserved: set[str],
) -> str:
    """Auto-suffix ``base_name`` so it collides with neither the DB nor
    other names already chosen in this same bulk batch."""
    candidate = (base_name or "").strip()[:60] or "Custom Metric"

    def _taken(name: str) -> bool:
        if name.lower() in reserved:
            return True
        return (
            db.query(Metric)
            .filter(
                and_(Metric.name == name, Metric.organization_id == organization_id)
            )
            .first()
            is not None
        )

    if not _taken(candidate):
        return candidate
    suffix = 2
    while _taken(f"{candidate} ({suffix})"):
        suffix += 1
    return f"{candidate} ({suffix})"


@router.post("/parse-bulk", response_model=MetricParseBulkResponse)
def parse_bulk_metric(
    req: MetricParseBulkRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Parse a multi-label rubric into a *list* of independent metric drafts.

    Each "Label #N" block becomes its own un-persisted draft metric the
    user can edit (name, type, capture_rationale, ...) before POSTing to
    ``/metrics`` individually. Defaults are chosen so the most common
    case ("did <X> happen?") is one click away: ``metric_type="boolean"``
    with ``capture_rationale=True``.

    The endpoint does NOT write to the database.
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    labels = _parse_label_blocks(req.prompt)
    if len(labels) < 1:
        # Format didn't match the deterministic regex; fall back to an LLM
        # parse so we still produce something useful for free-form rubrics.
        labels = _llm_parse_labels(req.prompt, organization_id, db)

    if len(labels) < 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract any labels from the prompt. Format each "
                "label as 'Label #N' followed by 'Label Name', 'Label "
                "Definition', and optionally 'Example (Optional)'."
            ),
        )

    # Deduplicate label names case-insensitively (preserve first occurrence)
    # so two identically-named labels in the rubric don't produce two
    # collidingly-named drafts.
    seen: set[str] = set()
    unique_labels: List[ParsedLabel] = []
    for label in labels:
        key = label.label_name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_labels.append(label)
    labels = unique_labels

    # When the user asks for a hierarchy we skip the per-child uniqueness
    # check against the existing org metrics: children are scoped to the
    # parent, not the org, so a child named "Pitch done" doesn't
    # collide with a top-level metric of the same name.
    parent_payload: Optional[MetricParseBulkParentDraft] = None
    build_hierarchy = bool(req.parent_name and req.parent_name.strip())
    if build_hierarchy:
        if not req.selection_mode:
            raise HTTPException(
                status_code=400,
                detail=(
                    "selection_mode is required when parent_name is "
                    "provided."
                ),
            )
        parent_name = req.parent_name.strip()
        # The parent metric DOES need to be unique among top-level
        # metrics in the org, so flag conflicts up front.
        existing_parent = (
            db.query(Metric)
            .filter(
                Metric.name == parent_name,
                Metric.organization_id == organization_id,
                Metric.parent_metric_id.is_(None),
            )
            .first()
        )
        if existing_parent:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"A top-level metric named '{parent_name}' already "
                    "exists."
                ),
            )
        parent_payload = MetricParseBulkParentDraft(
            name=parent_name,
            description=(req.parent_description or "").strip() or None,
            selection_mode=req.selection_mode,
            supported_surfaces=[req.surface],
            enabled_surfaces=[req.surface],
        )

    drafts: List[MetricDraft] = []
    chosen_names: set[str] = set()
    for label in labels:
        if build_hierarchy:
            # Children are scoped to the parent, so we just dedupe
            # within this batch (the unique-against-DB check is
            # skipped because the parent doesn't exist yet).
            candidate = (label.label_name or "").strip()[:60] or "Sub-metric"
            unique_name = candidate
            suffix = 2
            while unique_name.lower() in chosen_names:
                unique_name = f"{candidate} ({suffix})"
                suffix += 1
        else:
            unique_name = _ensure_unique_metric_name(
                label.label_name,
                organization_id,
                db,
                chosen_names,
            )
        chosen_names.add(unique_name.lower())
        drafts.append(
            MetricDraft(
                name=unique_name,
                description=_build_description_from_label(label),
                metric_type="boolean",
                custom_data_type="boolean",
                custom_config={},
                supported_surfaces=[req.surface],
                enabled_surfaces=[req.surface],
                capture_rationale=True,
                suggested_tags=[],
                source_label=label,
            )
        )

    return MetricParseBulkResponse(metrics=drafts, parent=parent_payload)


from app.core.auth.capabilities import METRICS_MANAGE, METRICS_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=METRICS_VIEW,
    manage_capability=METRICS_MANAGE,
)

