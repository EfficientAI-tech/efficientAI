"""Security remediation tests (Astra pentest fixes)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.api_rate_limit import check_auth_rate_limit, check_resource_create_rate_limit
from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.session_epoch import bump_user_session_epoch
from app.core.auth.tokens import create_access_token, decode_access_token
from app.services.ai.llm_config_safety import sanitize_client_llm_config
from app.services.telephony.exotel_client import ExotelInvalidContentError
from app.services.telephony.recording_download import (
    assert_outbound_http_url_safe,
    assert_recording_url_safe,
    assert_safe_provider_recording_url,
)


def test_user_update_forbids_email_field():
    from pydantic import ValidationError

    from app.models.schemas import UserUpdate

    with pytest.raises(ValidationError):
        UserUpdate(email="hacker@evil.com")


def test_sanitize_client_llm_config_strips_dangerous_keys():
    raw = {
        "temperature": 0.2,
        "api_base": "https://evil.example/v1",
        "api_key": "secret",
        "max_tokens": 100,
    }
    sanitized = sanitize_client_llm_config(raw)
    assert sanitized == {"temperature": 0.2, "max_tokens": 100}


def test_assert_safe_provider_recording_url_blocks_metadata_ip():
    with pytest.raises(ExotelInvalidContentError):
        assert_safe_provider_recording_url("http://169.254.169.254/latest/meta-data/")


def test_assert_recording_url_safe_blocks_metadata_ip():
    with pytest.raises(ExotelInvalidContentError):
        assert_recording_url_safe("http://169.254.169.254/latest/meta-data/", user_supplied=True)


def test_assert_outbound_http_url_safe_blocks_metadata_ip():
    with pytest.raises(ExotelInvalidContentError):
        assert_outbound_http_url_safe("http://169.254.169.254/")


def test_session_epoch_in_access_token():
    user_id = uuid4()
    org_id = uuid4()
    token, _, _ = create_access_token(
        user_id=user_id,
        organization_id=org_id,
        email="user@example.com",
        session_epoch=3,
    )
    claims = decode_access_token(token)
    assert claims["session_epoch"] == 3


def test_bump_user_session_epoch_increments():
    user = MagicMock()
    user.session_epoch = 1
    assert bump_user_session_epoch(user) == 2
    assert user.session_epoch == 2


def test_check_auth_rate_limit_allows_under_threshold():
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock(host="127.0.0.1")
    with patch("app.core.api_rate_limit._sliding_window_count", return_value=1):
        check_auth_rate_limit(request)


def test_check_resource_create_rate_limit_blocks_burst():
    principal = Principal(
        organization_id=uuid4(),
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=uuid4(),
        email="u@example.com",
    )
    with patch("app.core.api_rate_limit._sliding_window_count", return_value=999):
        with pytest.raises(HTTPException) as exc:
            check_resource_create_rate_limit(principal)
        assert exc.value.status_code == 429
