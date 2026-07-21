"""Load shard slice registry from catalog DB for router overrides."""

from __future__ import annotations

import uuid
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session


def load_slice_registry_for_import(
    db: Session,
    call_import_id: uuid.UUID | str,
) -> Dict[Tuple[str, int], str]:
    """
    Returns mapping (call_import_id str, slice_id) -> shard_id from
    ``call_import_shard_slices``. Empty when table missing or no rows.
    """
    from app.models.database import CallImportShardSlice

    cid = call_import_id if isinstance(call_import_id, uuid.UUID) else uuid.UUID(str(call_import_id))
    rows = db.execute(
        select(
            CallImportShardSlice.slice_id,
            CallImportShardSlice.shard_id,
        ).where(CallImportShardSlice.call_import_id == cid)
    ).all()
    key_prefix = str(cid)
    return {(key_prefix, int(slice_id)): str(shard_id) for slice_id, shard_id in rows}
