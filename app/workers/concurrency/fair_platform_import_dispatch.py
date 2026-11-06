"""Fair dispatch for platform historical import rows."""

from __future__ import annotations

from uuid import UUID

from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.database import CallImport, CallImportDiscoverySlice, CallImportRow, Workspace
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.config import celery_app

# Use the same queue as CSV call-import workers so local/docker setups that
# already run ``imports`` do not need a separate consumer (legacy tasks may
# still sit on the ``platform-imports`` Redis list — keep that on the worker -Q).
PLATFORM_IMPORTS_QUEUE = "imports"
PLATFORM_CONTROL_QUEUE = "import-control"
_BOOTSTRAP_DEDUPE_KEY = "platform_import:discovery_bootstrap"
_BOOTSTRAP_DEDUPE_SECONDS = 45
_DISPATCH_DEDUPE_KEY = "platform_import:row_dispatch"
_DISPATCH_BACKOFF_LEVEL_KEY = "platform_import:row_dispatch_backoff_level"
_DISPATCH_DEDUPE_SECONDS = 5
_DISPATCH_AT_CAPACITY_BACKOFF_SECONDS = 15
_DISPATCH_AT_CAPACITY_BACKOFF_MAX_SECONDS = 120

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis

        from app.config import settings

        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _reset_platform_dispatch_backoff_level() -> None:
    try:
        import redis

        _get_redis().delete(_DISPATCH_BACKOFF_LEVEL_KEY)
    except redis.RedisError:
        pass


def _bump_platform_dispatch_backoff_level() -> int:
    try:
        import redis

        level = int(_get_redis().incr(_DISPATCH_BACKOFF_LEVEL_KEY))
        _get_redis().expire(_DISPATCH_BACKOFF_LEVEL_KEY, 3600)
        return max(1, level)
    except redis.RedisError:
        return 1


def _pending_row_exists_on_session(row_db: Session, call_import_id: UUID) -> bool:
    return (
        row_db.query(CallImportRow.id)
        .filter(
            CallImportRow.call_import_id == call_import_id,
            CallImportRow.status == CallImportRowStatus.PENDING,
            CallImportRow.celery_task_id.is_(None),
        )
        .limit(1)
        .first()
        is not None
    )


def schedule_platform_discovery_bootstrap(*, countdown: int = 0) -> None:
    """Enqueue at most one global discovery bootstrap per short window."""
    try:
        import redis

        from app.config import settings

        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        if not client.set(_BOOTSTRAP_DEDUPE_KEY, "1", nx=True, ex=_BOOTSTRAP_DEDUPE_SECONDS):
            return
    except Exception as exc:
        logger.debug("platform discovery bootstrap dedupe skipped: {}", exc)

    try:
        discover_platform_slice_task.apply_async(
            kwargs={"bootstrap": True},
            queue=PLATFORM_CONTROL_QUEUE,
            countdown=countdown,
        )
    except Exception as exc:
        logger.warning("Failed to schedule platform discovery bootstrap: {}", exc)


def _enqueue_locked_slices(db: Session, rows: list[CallImportDiscoverySlice]) -> int:
    """Mark each pending day queued and publish one task that owns its lock.

    Status stays ``queued`` until that task starts. A second publish for the
    same day fails the lock and does not enter the broker.
    """
    from app.workers.concurrency.platform_import_limits import (
        acquire_slice_lock,
        discovery_enqueue_blocked,
        release_slice_lock,
    )

    if not rows or discovery_enqueue_blocked():
        return 0

    claimed: list[tuple[CallImportDiscoverySlice, str]] = []
    for slice_row in rows:
        owner = celery_uuid()
        if not acquire_slice_lock(slice_row.call_import_id, slice_row.slice_id, owner):
            logger.info(
                "platform discovery slice already locked import={} slice={}",
                slice_row.call_import_id,
                slice_row.slice_id,
            )
            continue
        slice_row.status = "queued"
        claimed.append((slice_row, owner))
    if not claimed:
        return 0
    db.commit()

    scheduled = 0
    for slice_row, owner in claimed:
        try:
            discover_platform_slice_task.apply_async(
                kwargs={
                    "call_import_id": str(slice_row.call_import_id),
                    "slice_id": slice_row.slice_id,
                },
                queue=PLATFORM_CONTROL_QUEUE,
                task_id=owner,
            )
            scheduled += 1
        except Exception:
            logger.exception(
                "platform discovery enqueue failed import={} slice={}",
                slice_row.call_import_id,
                slice_row.slice_id,
            )
            release_slice_lock(slice_row.call_import_id, slice_row.slice_id, owner)
            slice_row.status = "pending"
            db.commit()
    return scheduled


def _schedule_pending_slices_for_import(
    db: Session,
    call_import_id: UUID,
    *,
    limit: int = 2,
) -> int:
    rows = (
        db.query(CallImportDiscoverySlice)
        .filter(
            CallImportDiscoverySlice.call_import_id == call_import_id,
            CallImportDiscoverySlice.status == "pending",
        )
        .order_by(CallImportDiscoverySlice.slice_id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    return _enqueue_locked_slices(db, rows)


def _active_platform_imports(db: Session) -> list[CallImport]:
    return (
        db.query(CallImport)
        .join(Workspace, Workspace.id == CallImport.workspace_id)
        .filter(
            CallImport.source_format == "platform",
            CallImport.status != CallImportStatus.DELETING,
            CallImport.paused_at.is_(None),
            Workspace.is_active.is_(True),
        )
        .all()
    )


def _platform_import_ids_with_pending(db: Session, imports: list[CallImport]) -> list[UUID]:
    """Return platform imports that still have undispatched pending rows.

    Rows live on data shards when sharding is on; the catalog table is empty.
    """
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.sessions import is_sharding_enabled

    if not imports:
        return []
    by_id = {item.id: item for item in imports}
    if not is_sharding_enabled():
        rows = (
            db.query(CallImportRow.call_import_id)
            .filter(
                CallImportRow.call_import_id.in_(by_id.keys()),
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id.is_(None),
            )
            .distinct()
            .all()
        )
        return sorted(row[0] for row in rows if row[0] is not None)

    pending: set[UUID] = set()
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                shard_db.query(CallImportRow.call_import_id)
                .filter(
                    CallImportRow.call_import_id.in_(by_id.keys()),
                    CallImportRow.status == CallImportRowStatus.PENDING,
                    CallImportRow.celery_task_id.is_(None),
                )
                .distinct()
                .all()
            )
            pending.update(row[0] for row in rows if row[0] is not None)
        finally:
            shard_db.close()
    return sorted(pending)


def _rotate_import_ids(import_ids: list[UUID]) -> list[UUID]:
    if len(import_ids) < 2:
        return import_ids
    try:
        import redis

        from app.config import settings

        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        cursor = int(client.incr("platform_import:dispatch_rr") or 0)
    except Exception:
        cursor = 0
    offset = cursor % len(import_ids)
    return import_ids[offset:] + import_ids[:offset]


def _row_sessions_for_import(db: Session, call_import_id: UUID) -> list[Session]:
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.scatter_gather import shard_ids_for_import
    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        return [db]
    sessions: list[Session] = []
    for shard_id in shard_ids_for_import(db, call_import_id):
        factory = db_pool_manager.shard_session_factory(shard_id)
        sessions.append(factory())
    return sessions or [db]


def schedule_fair_platform_import_dispatch(*, countdown: int = 0) -> None:
    """Enqueue at most one row-dispatch task per dedupe window."""
    try:
        import redis

        ttl = max(_DISPATCH_DEDUPE_SECONDS, int(countdown) + 2)
        if not _get_redis().set(_DISPATCH_DEDUPE_KEY, "1", nx=True, ex=ttl):
            return
    except redis.RedisError as exc:
        logger.error("platform import dispatch dedupe failed: {}", exc)
        return

    try:
        dispatch_fair_platform_import_rows_task.apply_async(
            queue=PLATFORM_CONTROL_QUEUE,
            countdown=max(0, int(countdown)),
        )
    except Exception as exc:
        logger.warning("Failed to schedule platform import dispatch: {}", exc)


@celery_app.task(name="dispatch_fair_platform_import_rows", queue=PLATFORM_CONTROL_QUEUE)
def dispatch_fair_platform_import_rows_task() -> dict:
    from app.config import settings
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.scatter_gather import shard_ids_for_import
    from app.db_sharding.sessions import is_sharding_enabled
    from app.workers.concurrency.platform_import_dispatch import (
        clear_expired_platform_row_claims,
        try_dispatch_platform_import_row,
    )
    from app.workers.concurrency.platform_import_limits import (
        imports_queue_depth,
        lease_count,
        queue_depth,
    )

    db = SessionLocal()
    dispatched = 0
    dropped = 0
    hit_capacity = False
    try:
        imports = _active_platform_imports(db)
        platform_ids = {item.id for item in imports}
        if is_sharding_enabled():
            seen: set[str] = set()
            for call_import in imports:
                for shard_id in shard_ids_for_import(db, call_import.id):
                    if shard_id in seen:
                        continue
                    seen.add(shard_id)
                    factory = db_pool_manager.shard_session_factory(shard_id)
                    shard_db = factory()
                    try:
                        dropped += clear_expired_platform_row_claims(
                            shard_db, platform_import_ids=platform_ids
                        )
                    finally:
                        shard_db.close()
        else:
            dropped += clear_expired_platform_row_claims(db, platform_import_ids=platform_ids)

        by_id = {item.id: item for item in imports}
        pending_ids = _rotate_import_ids(_platform_import_ids_with_pending(db, imports))
        batch_limit = max(1, settings.PLATFORM_IMPORT_PER_IMPORT_INFLIGHT_LIMIT)
        for call_import_id in pending_ids:
            call_import = by_id[call_import_id]
            sessions = _row_sessions_for_import(db, call_import_id)
            try:
                for _ in range(batch_limit):
                    claimed = False
                    for row_db in sessions:
                        if try_dispatch_platform_import_row(db=row_db, call_import=call_import):
                            dispatched += 1
                            claimed = True
                            break
                    if not claimed:
                        for row_db in sessions:
                            if _pending_row_exists_on_session(row_db, call_import_id):
                                hit_capacity = True
                                break
                        break
            finally:
                for row_db in sessions:
                    if row_db is not db:
                        row_db.close()
        logger.info(
            "platform import dispatch tick dispatched={} dropped_expired={} imports_depth={} control_depth={} global_leases={}",
            dispatched,
            dropped,
            imports_queue_depth(),
            queue_depth(PLATFORM_CONTROL_QUEUE),
            lease_count("platform_import:lease:global"),
        )
        still_pending = _platform_import_ids_with_pending(db, imports)
        if dispatched > 0:
            _reset_platform_dispatch_backoff_level()
        if still_pending and (dispatched == 0 or hit_capacity):
            from app.workers.concurrency.import_retry_backoff import (
                import_dispatch_at_capacity_countdown,
            )

            level = _bump_platform_dispatch_backoff_level()
            backoff = import_dispatch_at_capacity_countdown(
                level=level,
                base_seconds=_DISPATCH_AT_CAPACITY_BACKOFF_SECONDS,
                max_seconds=_DISPATCH_AT_CAPACITY_BACKOFF_MAX_SECONDS,
            )
            schedule_fair_platform_import_dispatch(countdown=backoff)
        return {"status": "ok", "dispatched": dispatched, "dropped_expired": dropped}
    finally:
        db.close()


@celery_app.task(name="discover_platform_slice", queue=PLATFORM_CONTROL_QUEUE, bind=True)
def discover_platform_slice_task(
    self,
    call_import_id: str | None = None,
    slice_id: int | None = None,
    bootstrap: bool = False,
):
    from app.config import settings
    from app.models.database import CallImportDiscoverySlice
    from app.services.call_imports.platform_discovery import discover_platform_slice_chunk

    if call_import_id is not None and not bootstrap:
        logger.info(
            "platform import discovery slice import={} slice={}",
            call_import_id,
            slice_id,
        )

    db = SessionLocal()
    try:
        if bootstrap:
            from datetime import datetime, timedelta, timezone

            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=settings.PLATFORM_IMPORT_DISCOVERY_SLICE_STALE_MINUTES
            )
            from app.workers.concurrency.platform_import_limits import (
                force_release_slice_lock,
            )

            stale_running = (
                db.query(CallImportDiscoverySlice)
                .join(CallImport, CallImport.id == CallImportDiscoverySlice.call_import_id)
                .filter(
                    CallImport.source_format == "platform",
                    CallImport.status != CallImportStatus.DELETING,
                    CallImportDiscoverySlice.status.in_(("queued", "running")),
                    CallImportDiscoverySlice.updated_at < stale_cutoff,
                )
                .limit(8)
                .all()
            )
            if stale_running:
                for slice_row in stale_running:
                    force_release_slice_lock(slice_row.call_import_id, slice_row.slice_id)
                    slice_row.status = "pending"
                db.commit()

            pending_slices = (
                db.query(CallImportDiscoverySlice)
                .join(CallImport, CallImport.id == CallImportDiscoverySlice.call_import_id)
                .filter(
                    CallImport.source_format == "platform",
                    CallImport.status != CallImportStatus.DELETING,
                    CallImport.paused_at.is_(None),
                    CallImportDiscoverySlice.status == "pending",
                )
                .order_by(CallImportDiscoverySlice.slice_id.asc())
                .limit(4)
                .with_for_update(skip_locked=True)
                .all()
            )
            scheduled = _enqueue_locked_slices(db, pending_slices)
            if scheduled:
                logger.info("platform import discovery bootstrap scheduled={}", scheduled)
            return {"bootstrapped": scheduled}

        if call_import_id is None or slice_id is None:
            return {"status": "skipped"}

        import_uuid = UUID(call_import_id)
        existing = (
            db.query(CallImportDiscoverySlice)
            .filter(
                CallImportDiscoverySlice.call_import_id == import_uuid,
                CallImportDiscoverySlice.slice_id == slice_id,
            )
            .first()
        )
        if existing is None or existing.status in {"completed", "failed"}:
            return {"more": False, "skipped": True}

        parent = db.query(CallImport).filter(CallImport.id == import_uuid).first()
        if (
            parent is None
            or parent.status == CallImportStatus.DELETING
            or parent.paused_at is not None
        ):
            from app.workers.concurrency.platform_import_limits import release_slice_lock

            release_slice_lock(import_uuid, slice_id, str(self.request.id or ""))
            if existing.status in {"queued", "running"}:
                existing.status = "pending"
                db.commit()
            return {"more": False, "skipped": True}

        from app.workers.concurrency.platform_import_limits import (
            release_slice_lock,
            slice_lock_owner,
            transfer_slice_lock,
        )

        owner = str(self.request.id or "")
        if slice_lock_owner(import_uuid, slice_id) != owner:
            logger.info(
                "platform discovery duplicate ignored import={} slice={} task={}",
                call_import_id,
                slice_id,
                owner,
            )
            return {"more": False, "skipped": True, "reason": "locked"}

        try:
            chunk = discover_platform_slice_chunk(
                db,
                import_uuid,
                slice_id,
                page_budget=settings.PLATFORM_IMPORT_DISCOVERY_PAGE_BUDGET,
            )
        except Exception:
            logger.exception(
                "platform discovery slice crashed import={} slice={}",
                call_import_id,
                slice_id,
            )
            release_slice_lock(import_uuid, slice_id, owner)
            if existing.status in {"queued", "running"}:
                existing.attempts = int(existing.attempts or 0) + 1
                existing.status = "failed" if existing.attempts >= 5 else "pending"
                db.commit()
            from app.services.call_imports.platform_discovery import (
                finalize_platform_discovery_if_complete,
            )

            finalize_platform_discovery_if_complete(db, import_uuid)
            return {"more": False, "skipped": True}
        more = chunk.get("more") if isinstance(chunk, dict) else bool(chunk)
        wait = int(chunk.get("wait") or 1) if isinstance(chunk, dict) else 1
        if more:
            from app.workers.concurrency.platform_import_limits import (
                discovery_enqueue_blocked,
            )

            if discovery_enqueue_blocked():
                release_slice_lock(import_uuid, slice_id, owner)
                existing.status = "pending"
                db.commit()
                return {"more": False, "deferred": True}
            next_owner = celery_uuid()
            if transfer_slice_lock(import_uuid, slice_id, owner, next_owner):
                discover_platform_slice_task.apply_async(
                    kwargs={"call_import_id": call_import_id, "slice_id": slice_id},
                    queue=PLATFORM_CONTROL_QUEUE,
                    task_id=next_owner,
                    countdown=max(1, wait),
                )
            else:
                logger.error(
                    "platform discovery continuation lost lock import={} slice={}",
                    call_import_id,
                    slice_id,
                )
            return {"more": True}

        release_slice_lock(import_uuid, slice_id, owner)
        finished = (
            db.query(CallImportDiscoverySlice)
            .filter(
                CallImportDiscoverySlice.call_import_id == import_uuid,
                CallImportDiscoverySlice.slice_id == slice_id,
            )
            .first()
        )
        parent = db.query(CallImport).filter(CallImport.id == import_uuid).first()
        if (
            finished is not None
            and finished.status in {"completed", "failed"}
            and parent is not None
            and parent.status != CallImportStatus.DELETING
            and parent.paused_at is None
        ):
            _schedule_pending_slices_for_import(db, import_uuid, limit=2)
            schedule_fair_platform_import_dispatch(countdown=1)
        return {"more": False}
    finally:
        db.close()
