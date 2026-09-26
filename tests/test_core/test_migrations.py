from unittest.mock import patch

from sqlalchemy.engine import make_url


def test_engine_role_uses_url_object_not_masked_string():
    from app.core.migrations import _engine_role_for_url

    catalog = "postgresql://user:pass@localhost:5432/efficientai"
    catalog_url = make_url(catalog)

    class _Settings:
        DB_SHARDING_ENABLED = True
        DB_CATALOG_URL = catalog
        DATABASE_URL = catalog

    with patch("app.config.settings", _Settings()):
        assert _engine_role_for_url(catalog_url) == "catalog"
        assert _engine_role_for_url(str(catalog_url)) == "shard"
