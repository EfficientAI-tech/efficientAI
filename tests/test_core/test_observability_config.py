from app.config import Settings, load_config_from_file, settings


def test_observability_defaults_to_disabled():
    isolated = Settings(_env_file=None)

    assert isolated.OBSERVABILITY_ENABLED is False
    assert isolated.LOKI_ENABLED is False


def test_observability_yaml_enables_app_and_loki(tmp_path):
    originals = {
        "OBSERVABILITY_ENABLED": settings.OBSERVABILITY_ENABLED,
        "LOKI_ENABLED": settings.LOKI_ENABLED,
        "LOKI_MULTI_TENANT": settings.LOKI_MULTI_TENANT,
        "LOKI_URL": settings.LOKI_URL,
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
observability:
  enabled: true
  loki:
    enabled: true
    url: "http://custom-loki:3100"
    multi_tenant: true
""".strip(),
        encoding="utf-8",
    )

    try:
        load_config_from_file(str(config_file))

        assert settings.OBSERVABILITY_ENABLED is True
        assert settings.LOKI_ENABLED is True
        assert settings.LOKI_MULTI_TENANT is True
        assert settings.LOKI_URL == "http://custom-loki:3100"
    finally:
        for name, value in originals.items():
            setattr(settings, name, value)
