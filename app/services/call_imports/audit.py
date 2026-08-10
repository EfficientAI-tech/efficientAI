"""Actor stamping and email resolution for call import audit fields."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.models.database import CallImport, CallImportEvaluation, User


def stamp_call_import_actor(
    call_import: CallImport,
    principal: Principal,
    *,
    creating: bool = False,
) -> None:
    if creating and principal.user_id is not None:
        call_import.created_by_user_id = principal.user_id
    if principal.user_id is not None:
        call_import.last_updated_by_user_id = principal.user_id


def stamp_evaluation_actor(
    evaluation: CallImportEvaluation,
    principal: Principal,
    *,
    creating: bool = False,
) -> None:
    if creating and principal.user_id is not None:
        evaluation.created_by_user_id = principal.user_id
    if principal.user_id is not None:
        evaluation.last_updated_by_user_id = principal.user_id


def user_ids_from_call_imports(imports: Iterable[CallImport]) -> Set[UUID]:
    ids: Set[UUID] = set()
    for row in imports:
        created_by = getattr(row, "created_by_user_id", None)
        updated_by = getattr(row, "last_updated_by_user_id", None)
        if created_by is not None:
            ids.add(created_by)
        if updated_by is not None:
            ids.add(updated_by)
    return ids


def user_ids_from_evaluations(
    evaluations: Iterable[CallImportEvaluation],
) -> Set[UUID]:
    ids: Set[UUID] = set()
    for row in evaluations:
        created_by = getattr(row, "created_by_user_id", None)
        updated_by = getattr(row, "last_updated_by_user_id", None)
        if created_by is not None:
            ids.add(created_by)
        if updated_by is not None:
            ids.add(updated_by)
    return ids


def emails_for_user_ids(db: Session, user_ids: Iterable[UUID]) -> Dict[UUID, str]:
    unique = {uid for uid in user_ids if uid is not None}
    if not unique:
        return {}
    rows = db.query(User.id, User.email).filter(User.id.in_(unique)).all()
    return {row.id: row.email for row in rows if row.email}


def actor_emails_for_call_import(
    call_import: CallImport,
    email_by_id: Dict[UUID, str],
) -> Tuple[Optional[str], Optional[str]]:
    created = (
        email_by_id.get(call_import.created_by_user_id)
        if call_import.created_by_user_id
        else None
    )
    updated = (
        email_by_id.get(call_import.last_updated_by_user_id)
        if call_import.last_updated_by_user_id
        else None
    )
    return created, updated


def actor_emails_for_evaluation(
    evaluation: CallImportEvaluation,
    email_by_id: Dict[UUID, str],
) -> Tuple[Optional[str], Optional[str]]:
    created = (
        email_by_id.get(evaluation.created_by_user_id)
        if evaluation.created_by_user_id
        else None
    )
    updated = (
        email_by_id.get(evaluation.last_updated_by_user_id)
        if evaluation.last_updated_by_user_id
        else None
    )
    return created, updated
