"""Unit tests for shard slice rebalance / backfill tooling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.db_sharding.rebalance import (
    RebalanceError,
    RebalancePlan,
    SliceInfo,
    assert_import_rebalance_ready,
    build_rebalance_plan,
    execute_rebalance_slices,
    filter_unlocked_call_import_ids,
    list_shard_slices,
)
from app.models.enums import CallImportStatus


def test_slice_info_row_count():
    info = SliceInfo(slice_id=0, shard_id="s1", row_index_min=0, row_index_max=499)
    assert info.row_count == 500


def test_list_shard_slices_maps_registry_rows():
    catalog_db = MagicMock()
    call_import_id = uuid4()
    catalog_db.execute.return_value.all.return_value = [
        (0, "data-shard-01", 0, 499),
        (1, "data-shard-02", 500, 999),
    ]
    slices = list_shard_slices(catalog_db, call_import_id)
    assert len(slices) == 2
    assert slices[0].shard_id == "data-shard-01"
    assert slices[1].row_index_min == 500


def test_build_rebalance_plan_filters_by_shard_and_slice():
    catalog_db = MagicMock()
    call_import_id = uuid4()
    slices = [
        SliceInfo(0, "data-shard-01", 0, 499),
        SliceInfo(1, "data-shard-01", 500, 999),
        SliceInfo(2, "data-shard-02", 1000, 1499),
    ]

    with patch("app.db_sharding.rebalance.is_sharding_enabled", return_value=True):
        with patch("app.db_sharding.rebalance.list_shard_slices", return_value=slices):
            with patch(
                "app.db_sharding.rebalance._evaluation_ids_for_import",
                return_value=[],
            ):
                with patch(
                    "app.db_sharding.rebalance._count_rows_on_shard",
                    return_value=(500, 0),
                ):
                    with patch(
                        "app.db_sharding.rebalance._configured_shard_ids",
                        return_value={"data-shard-01", "data-shard-02"},
                    ):
                        plan = build_rebalance_plan(
                            catalog_db,
                            call_import_id,
                            from_shard_id="data-shard-01",
                            to_shard_id="data-shard-02",
                            slice_ids=[1],
                        )

    assert plan.from_shard_id == "data-shard-01"
    assert plan.to_shard_id == "data-shard-02"
    assert len(plan.slices) == 1
    assert plan.slices[0].slice_id == 1
    assert plan.import_row_count == 500


def test_build_rebalance_plan_rejects_same_shard():
    catalog_db = MagicMock()
    with patch("app.db_sharding.rebalance.is_sharding_enabled", return_value=True):
        with patch(
            "app.db_sharding.rebalance._configured_shard_ids",
            return_value={"data-shard-01"},
        ):
            with pytest.raises(RebalanceError, match="must differ"):
                build_rebalance_plan(
                    catalog_db,
                    uuid4(),
                    from_shard_id="data-shard-01",
                    to_shard_id="data-shard-01",
                )


def test_assert_import_rebalance_ready_blocks_processing():
    catalog_db = MagicMock()
    call_import = MagicMock(status=CallImportStatus.PROCESSING)
    catalog_db.query.return_value.filter.return_value.first.return_value = call_import

    with pytest.raises(RebalanceError, match="terminal status"):
        assert_import_rebalance_ready(catalog_db, uuid4(), force=False)


def test_execute_rebalance_slices_dry_run_skips_copy():
    catalog_db = MagicMock()
    plan = RebalancePlan(
        call_import_id=uuid4(),
        from_shard_id="data-shard-01",
        to_shard_id="data-shard-02",
        slices=(SliceInfo(0, "data-shard-01", 0, 10),),
        import_row_count=11,
        eval_row_count=3,
    )

    with patch("app.db_sharding.rebalance.is_sharding_enabled", return_value=True):
        with patch("app.db_sharding.rebalance.assert_import_rebalance_ready"):
            with patch("app.db_sharding.rebalance._copy_rows_between_shards") as copy_mock:
                result = execute_rebalance_slices(catalog_db, plan, dry_run=True)

    assert result.dry_run is True
    assert result.import_rows_moved == 11
    copy_mock.assert_not_called()
    catalog_db.commit.assert_not_called()


def test_filter_unlocked_call_import_ids():
    locked_id = uuid4()
    open_id = uuid4()
    with patch(
        "app.db_sharding.rebalance.is_import_rebalance_locked",
        side_effect=lambda cid: cid == locked_id,
    ):
        out = filter_unlocked_call_import_ids([locked_id, open_id])
    assert out == [open_id]
