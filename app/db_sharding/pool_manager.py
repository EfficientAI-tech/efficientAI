"""SQLAlchemy engines and session factories for catalog + row shards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db_sharding.router import ShardRouter


@dataclass(frozen=True)
class ShardEntry:
    id: str
    url: str


class DatabasePoolManager:
    """Lazy-init pools from application settings."""

    def __init__(self) -> None:
        self._initialized = False
        self._sharding_enabled = False
        self._catalog_engine: Optional[Engine] = None
        self._legacy_engine: Optional[Engine] = None
        self._shard_engines: Dict[str, Engine] = {}
        self._catalog_session_factory: Optional[sessionmaker] = None
        self._legacy_session_factory: Optional[sessionmaker] = None
        self._shard_session_factories: Dict[str, sessionmaker] = {}
        self._router: Optional[ShardRouter] = None
        self._shard_entries: List[ShardEntry] = []

    @property
    def sharding_enabled(self) -> bool:
        self._ensure_initialized()
        return self._sharding_enabled

    @property
    def router(self) -> Optional[ShardRouter]:
        self._ensure_initialized()
        return self._router

    @property
    def catalog_engine(self) -> Engine:
        self._ensure_initialized()
        if self._sharding_enabled:
            assert self._catalog_engine is not None
            return self._catalog_engine
        assert self._legacy_engine is not None
        return self._legacy_engine

    def shard_engine(self, shard_id: str) -> Engine:
        self._ensure_initialized()
        if not self._sharding_enabled:
            return self.catalog_engine
        try:
            return self._shard_engines[shard_id]
        except KeyError as exc:
            raise KeyError(f"unknown shard id: {shard_id}") from exc

    def catalog_session_factory(self) -> sessionmaker:
        self._ensure_initialized()
        if self._sharding_enabled:
            assert self._catalog_session_factory is not None
            return self._catalog_session_factory
        assert self._legacy_session_factory is not None
        return self._legacy_session_factory

    def shard_session_factory(self, shard_id: str) -> sessionmaker:
        self._ensure_initialized()
        if not self._sharding_enabled:
            return self.catalog_session_factory()
        return self._shard_session_factories[shard_id]

    def all_engines_for_migrations(self) -> List[Engine]:
        """Engines that should receive schema migrations (unique URLs)."""
        self._ensure_initialized()
        seen: set[str] = set()
        engines: List[Engine] = []
        for eng in [self.catalog_engine, *self._shard_engines.values()]:
            url = str(eng.url)
            if url in seen:
                continue
            seen.add(url)
            engines.append(eng)
        return engines

    def reset(self) -> None:
        """Dispose engines (tests)."""
        for eng in list(self._shard_engines.values()):
            eng.dispose()
        if self._catalog_engine is not None:
            self._catalog_engine.dispose()
        if self._legacy_engine is not None:
            self._legacy_engine.dispose()
        self._initialized = False
        self._catalog_engine = None
        self._legacy_engine = None
        self._shard_engines.clear()
        self._catalog_session_factory = None
        self._legacy_session_factory = None
        self._shard_session_factories.clear()
        self._router = None
        self._shard_entries: List[ShardEntry] = []
        self._sharding_enabled = False

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            from app.config import settings

            self._configure_from_settings(settings)

    def _configure_from_settings(self, settings) -> None:
        pool_size = int(getattr(settings, "DB_POOL_SIZE", 10))
        max_overflow = int(getattr(settings, "DB_MAX_OVERFLOW", 20))

        def make_engine(url: str) -> Engine:
            return create_engine(url, **_create_engine_kwargs(url, pool_size, max_overflow))

        enabled = bool(getattr(settings, "DB_SHARDING_ENABLED", False))
        database_url = settings.DATABASE_URL
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured")

        if not enabled:
            self._legacy_engine = make_engine(database_url)
            self._legacy_session_factory = sessionmaker(
                autocommit=False, autoflush=False, bind=self._legacy_engine
            )
            self._sharding_enabled = False
            self._initialized = True
            return

        catalog_url = getattr(settings, "DB_CATALOG_URL", None) or database_url
        shard_entries = _parse_shard_entries(settings, fallback_url=database_url)
        chunk_size = int(getattr(settings, "DB_SHARD_ROW_CHUNK_SIZE", 500))
        shard_pool_size = pool_size
        shard_max_overflow = max_overflow
        if len(shard_entries) > 1:
            per_shard = max(4, pool_size // len(shard_entries))
            shard_pool_size = max(8, per_shard)
            shard_max_overflow = max(8, max_overflow // len(shard_entries))

        self._catalog_engine = make_engine(catalog_url)
        self._catalog_session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self._catalog_engine
        )
        self._shard_entries = shard_entries
        for entry in shard_entries:
            eng = create_engine(
                entry.url,
                **_create_engine_kwargs(entry.url, shard_pool_size, shard_max_overflow),
            )
            self._shard_engines[entry.id] = eng
            self._shard_session_factories[entry.id] = sessionmaker(
                autocommit=False, autoflush=False, bind=eng
            )
        self._router = ShardRouter(
            [e.id for e in shard_entries],
            row_chunk_size=chunk_size,
        )
        self._sharding_enabled = True
        self._initialized = True


def _create_engine_kwargs(url: str, pool_size: int, max_overflow: int) -> dict:
    """Dialect-appropriate kwargs (SQLite tests use SingletonThreadPool)."""
    dialect_name = make_url(url).get_backend_name()
    if dialect_name == "sqlite":
        return {"pool_pre_ping": True}
    return {
        "pool_pre_ping": True,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "connect_args": {"options": "-c timezone=UTC"},
    }


def _parse_shard_entries(settings, *, fallback_url: str) -> List[ShardEntry]:
    raw = getattr(settings, "DB_SHARD_ENTRIES", None) or []
    entries: List[ShardEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        shard_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if shard_id and url:
            entries.append(ShardEntry(id=shard_id, url=url))
    if not entries:
        entries.append(ShardEntry(id="data-shard-01", url=fallback_url))
    return entries


db_pool_manager = DatabasePoolManager()


def open_catalog_session() -> Session:
    factory = db_pool_manager.catalog_session_factory()
    return factory()


def open_row_shard_session(
    call_import_id,
    row_index: int,
) -> tuple[Session, str]:
    manager = db_pool_manager
    if not manager.sharding_enabled:
        return open_catalog_session(), "legacy"
    router = manager.router
    assert router is not None
    shard_id = router.shard_id_for_row(call_import_id, row_index)
    session = manager.shard_session_factory(shard_id)()
    return session, shard_id
