"""Unit tests for blob path helpers."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.storage.blob_paths import assert_key_belongs_to_org


def test_assert_key_belongs_to_org_accepts_valid_key():
    org_id = uuid4()
    key = f"audio/organizations/{org_id}/audio/test.wav"
    assert (
        assert_key_belongs_to_org(key, org_id, storage_prefix="audio/")
        == key
    )


def test_assert_key_belongs_to_org_rejects_other_org():
    org_id = uuid4()
    other_org_id = uuid4()
    key = f"audio/organizations/{other_org_id}/audio/test.wav"
    with pytest.raises(HTTPException) as exc_info:
        assert_key_belongs_to_org(key, org_id, storage_prefix="audio/")
    assert exc_info.value.status_code == 403


def test_assert_key_belongs_to_org_rejects_path_traversal():
    org_id = uuid4()
    key = f"audio/organizations/{org_id}/../other-org/secret.wav"
    with pytest.raises(HTTPException) as exc_info:
        assert_key_belongs_to_org(key, org_id, storage_prefix="audio/")
    assert exc_info.value.status_code == 403


def test_assert_key_belongs_to_org_decodes_percent_encoded_key():
    org_id = uuid4()
    raw_key = f"audio/organizations/{org_id}/audio/test.wav"
    encoded_key = raw_key.replace("/", "%2F")
    assert (
        assert_key_belongs_to_org(
            encoded_key, org_id, storage_prefix="audio/", decode=True
        )
        == raw_key
    )
