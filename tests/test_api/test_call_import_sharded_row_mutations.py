"""Tests for shard-aware single-row call import mutations.

After DB sharding, ``call_import_rows`` live on shard databases. Mutation
routes must locate rows via :func:`locate_call_import_row` rather than
querying the catalog session from ``get_db``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth.principal import AuthMethod, Principal
from app.api.v1.routes.call_imports import (
    cancel_call_import_row_diarisation,
    toggle_call_import_row_speaker_swap,
)
from app.models.enums import CallImportRowStatus


def _fake_call_import(call_import_id, organization_id):
    return SimpleNamespace(id=call_import_id, organization_id=organization_id)


def _fake_catalog_db(call_import):
    catalog_db = MagicMock()
    catalog_db.query.return_value.filter.return_value.first.return_value = call_import
    return catalog_db


def _test_principal(organization_id):
    return Principal(
        organization_id=organization_id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=uuid4(),
    )


def _fake_shard_row(
    *,
    call_import_id,
    organization_id,
    row_id,
    diarised_segments=None,
    diarised_speaker_swap=False,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=row_id,
        call_import_id=call_import_id,
        organization_id=organization_id,
        row_index=0,
        conversation_id="conv-1",
        diarised_segments=diarised_segments
        if diarised_segments is not None
        else [{"speaker": "agent", "text": "Hello"}],
        diarised_speaker_swap=diarised_speaker_swap,
        diarised_transcript="agent: Hello",
        diarised_transcript_status="completed",
        celery_task_id=None,
        status=CallImportRowStatus.COMPLETED,
        attempts=1,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_toggle_speaker_swap_commits_on_shard_session(monkeypatch):
    call_import_id = uuid4()
    row_id = uuid4()
    organization_id = uuid4()
    fake_row = _fake_shard_row(
        call_import_id=call_import_id,
        organization_id=organization_id,
        row_id=row_id,
    )

    committed: list[str] = []
    row_db = MagicMock()
    row_db.commit.side_effect = lambda: committed.append("commit")
    row_db.refresh.side_effect = lambda _row: None
    extra_catalog = MagicMock()

    def fake_locate(_row_id):
        assert _row_id == row_id
        return row_db, extra_catalog, fake_row, "shard-0"

    closed: list[tuple] = []
    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        fake_locate,
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.close_row_sessions",
        lambda row_db_arg, catalog_arg: closed.append((row_db_arg, catalog_arg)),
    )

    result = await toggle_call_import_row_speaker_swap(
        call_import_id=call_import_id,
        row_id=row_id,
        api_key="",
        organization_id=organization_id,
        principal=_test_principal(organization_id),
        db=_fake_catalog_db(_fake_call_import(call_import_id, organization_id)),
    )

    assert fake_row.diarised_speaker_swap is True
    assert fake_row.diarised_transcript == "user: Hello"
    assert committed == ["commit"]
    assert closed == [(row_db, extra_catalog)]
    assert result.diarised_speaker_swap is True
    assert result.diarised_transcript == "user: Hello"


@pytest.mark.asyncio
async def test_toggle_speaker_swap_not_found_on_shard(monkeypatch):
    call_import_id = uuid4()
    row_id = uuid4()
    organization_id = uuid4()

    def fake_locate(_row_id):
        raise LookupError(f"call_import_row {row_id} not found on any shard")

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        fake_locate,
    )

    with pytest.raises(HTTPException) as exc_info:
        await toggle_call_import_row_speaker_swap(
            call_import_id=call_import_id,
            row_id=row_id,
            api_key="",
            organization_id=organization_id,
            principal=_test_principal(organization_id),
            db=_fake_catalog_db(_fake_call_import(call_import_id, organization_id)),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Call import row not found"


@pytest.mark.asyncio
async def test_cancel_diarisation_commits_on_shard_session(monkeypatch):
    call_import_id = uuid4()
    row_id = uuid4()
    organization_id = uuid4()
    fake_row = _fake_shard_row(
        call_import_id=call_import_id,
        organization_id=organization_id,
        row_id=row_id,
    )
    fake_row.diarised_transcript_status = "running"

    committed: list[str] = []
    row_db = MagicMock()
    row_db.commit.side_effect = lambda: committed.append("commit")
    row_db.refresh.side_effect = lambda _row: None
    extra_catalog = MagicMock()

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        lambda _row_id: (row_db, extra_catalog, fake_row, "shard-0"),
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.close_row_sessions",
        lambda *_args: None,
    )

    from app.api.v1.routes import call_imports as routes

    monkeypatch.setattr(
        routes,
        "_apply_diarisation_cancel",
        lambda rows: (1, 0),
    )

    result = await cancel_call_import_row_diarisation(
        call_import_id=call_import_id,
        row_id=row_id,
        api_key="",
        organization_id=organization_id,
        principal=_test_principal(organization_id),
        db=_fake_catalog_db(_fake_call_import(call_import_id, organization_id)),
    )

    assert committed == ["commit"]
    assert result.id == row_id
