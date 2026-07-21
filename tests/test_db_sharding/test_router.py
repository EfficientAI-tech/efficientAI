import uuid

import pytest

from app.db_sharding.router import ShardRouter


def test_slice_id_for_row_index():
    router = ShardRouter(["a", "b"], row_chunk_size=500)
    assert router.slice_id_for_row_index(0) == 0
    assert router.slice_id_for_row_index(499) == 0
    assert router.slice_id_for_row_index(500) == 1


def test_single_shard_always_same():
    router = ShardRouter(["only"], row_chunk_size=100)
    cid = uuid.uuid4()
    for idx in (0, 50, 9999):
        assert router.shard_id_for_row(cid, idx) == "only"


def test_deterministic_routing():
    router = ShardRouter(["s1", "s2", "s3"], row_chunk_size=500)
    cid = uuid.uuid4()
    first = router.shard_id_for_row(cid, 1200)
    assert first in ("s1", "s2", "s3")
    assert router.shard_id_for_row(cid, 1200) == first
    assert router.shard_id_for_row(str(cid), 1200) == first


def test_registry_override():
    router = ShardRouter(["s1", "s2"], row_chunk_size=500)
    cid = uuid.uuid4()
    slice_id = router.slice_id_for_row_index(750)
    assert slice_id == 1
    hashed = router.shard_id_for_slice(cid, slice_id)
    registry = {(str(cid), slice_id): "s2"}
    assert router.shard_id_for_row(cid, 750, slice_registry=registry) == "s2"
    assert router.shard_id_for_row(cid, 750) == hashed


def test_invalid_chunk_size():
    with pytest.raises(ValueError):
        ShardRouter(["a"], row_chunk_size=0)


def test_empty_shard_list():
    with pytest.raises(ValueError):
        ShardRouter([])
