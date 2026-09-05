"""Unit tests for ambient library preview URL generation."""

from uuid import uuid4

import pytest


def test_ambient_library_preview_url_handler(monkeypatch):
    from app.api.v1.routes import personas as personas_routes

    asset_id = uuid4()
    expected_key = f"ambient/library/{asset_id}.wav"

    class _Row:
        s3_key = expected_key

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return _Row()

    class _Db:
        def query(self, _model):
            return _Query()

    monkeypatch.setattr(personas_routes.s3_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        personas_routes.s3_service,
        "generate_presigned_url_by_key",
        lambda key, expiration=3600: f"https://storage.example/{key}?exp={expiration}",
    )

    import asyncio

    result = asyncio.run(
        personas_routes.get_ambient_library_preview_url(
            asset_id=asset_id,
            expiration=3600,
            organization_id=uuid4(),
            workspace_id=uuid4(),
            db=_Db(),
            api_key="test-key",
        )
    )

    assert result.url == f"https://storage.example/{expected_key}?exp=3600"
    assert result.expires_in == 3600


def test_ambient_library_preview_url_not_found(monkeypatch):
    from app.api.v1.routes import personas as personas_routes
    from fastapi import HTTPException

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, _model):
            return _Query()

    monkeypatch.setattr(personas_routes.s3_service, "is_enabled", lambda: True)

    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            personas_routes.get_ambient_library_preview_url(
                asset_id=uuid4(),
                expiration=3600,
                organization_id=uuid4(),
                workspace_id=uuid4(),
                db=_Db(),
                api_key="test-key",
            )
        )

    assert exc.value.status_code == 404
