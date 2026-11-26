from __future__ import annotations

import pytest

from efficientai_sdk import DEFAULT_BASE_URL, ConfigurationError, EfficientAI
from efficientai_sdk._config import normalize_base_url, resolve_config


def test_missing_api_key_raises() -> None:
    with pytest.raises(ConfigurationError, match="EFFICIENTAI_API_KEY"):
        EfficientAI()


def test_dotenv_file_is_loaded(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import efficientai_sdk._config as cfgmod

    monkeypatch.delenv("EFFICIENTAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EFFICIENTAI_API_KEY=dotenv-key\n", encoding="utf-8")
    cfgmod._dotenv_loaded = False
    cfg = resolve_config()
    assert cfg.api_key == "dotenv-key"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_KEY", " env-key ")
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("EFFICIENTAI_BASE_URL", "https://self-hosted.example/")
    cfg = resolve_config()
    assert cfg.api_key == "env-key"
    assert cfg.workspace_id == "ws-1"
    assert cfg.base_url == "https://self-hosted.example"


def test_arguments_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "env-key")
    monkeypatch.setenv("EFFICIENTAI_BASE_URL", "https://env.example")
    cfg = resolve_config(api_key="arg-key", base_url="https://arg.example")
    assert cfg.api_key == "arg-key"
    assert cfg.base_url == "https://arg.example"


def test_legacy_base_url_env_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_BASE", "http://localhost:8000")
    assert resolve_config(api_key="k").base_url == "http://localhost:8000"


def test_default_base_url() -> None:
    assert resolve_config(api_key="k").base_url == DEFAULT_BASE_URL == "http://localhost:8000"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://x.example", "https://x.example"),
        ("https://x.example/", "https://x.example"),
        ("https://x.example/api/v1", "https://x.example"),
        ("https://x.example/api/v1/", "https://x.example"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected


def test_custom_api_prefix_strips_from_base_url() -> None:
    cfg = resolve_config(api_key="k", base_url="https://x.example/api", api_prefix="/api")
    assert cfg.base_url == "https://x.example"
    assert cfg.api_path("auth/validate") == "/api/auth/validate"


def test_api_hostname_is_not_stripped_as_prefix() -> None:
    cfg = resolve_config(api_key="k", base_url="http://api", api_prefix="/api")
    assert cfg.base_url == "http://api"


def test_base_url_requires_scheme() -> None:
    with pytest.raises(ConfigurationError):
        normalize_base_url("x.example")


@pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"max_retries": -1}])
def test_invalid_numbers(kwargs: dict[str, float]) -> None:
    with pytest.raises(ConfigurationError):
        resolve_config(api_key="k", **kwargs)  # type: ignore[arg-type]


def test_repr_hides_api_key() -> None:
    cfg = resolve_config(api_key="super-secret")
    assert "super-secret" not in repr(cfg)
    assert "super-secret" not in repr(EfficientAI(api_key="super-secret"))
