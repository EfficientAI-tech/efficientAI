"""RS256 session JWT key loading and token round-trip."""

from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.config import settings, validate_auth_configuration
from app.core.auth import jwt_keys
from app.core.auth.jwt_keys import SESSION_JWT_ALGORITHM, ensure_session_jwt_keys
from app.core.auth.tokens import ISSUER, create_access_token, decode_access_token


def _rsa_pem_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


@pytest.fixture
def reset_jwt_key_cache():
    jwt_keys._signing_key_pem = None
    jwt_keys._verification_key_pem = None
    jwt_keys._ephemeral_generated = False
    yield
    jwt_keys._signing_key_pem = None
    jwt_keys._verification_key_pem = None
    jwt_keys._ephemeral_generated = False


def test_session_token_uses_rs256(reset_jwt_key_cache, monkeypatch):
    private_pem, public_pem = _rsa_pem_pair()
    monkeypatch.setattr(settings, "AUTH_JWT_PRIVATE_KEY_PEM", private_pem)
    monkeypatch.setattr(settings, "AUTH_JWT_PUBLIC_KEY_PEM", public_pem)
    ensure_session_jwt_keys()

    token, _, _ = create_access_token(
        user_id=uuid4(),
        organization_id=uuid4(),
        email="user@example.com",
    )
    header = jwt.get_unverified_header(token)
    assert header["alg"] == SESSION_JWT_ALGORITHM
    claims = decode_access_token(token)
    assert claims["iss"] == ISSUER
    assert claims["email"] == "user@example.com"


def test_validate_auth_requires_trusted_hosts_when_not_debug(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 32)
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(settings, "TRUSTED_HOSTS", [])
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_AUTO_FROM_FRONTEND", False)
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_EXPLICIT", [])
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_FROM_ENV", [])
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key"])

    with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
        validate_auth_configuration()


def test_validate_auth_requires_jwt_pem_when_local_password_and_not_debug(
    monkeypatch, reset_jwt_key_cache
):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 32)
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_AUTO_FROM_FRONTEND", True)
    monkeypatch.setattr(settings, "AUTH_JWT_PRIVATE_KEY_PEM", "")
    monkeypatch.setattr(settings, "AUTH_JWT_PUBLIC_KEY_PEM", "")
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["local_password"])

    with pytest.raises(RuntimeError, match="AUTH_JWT_PRIVATE_KEY_PEM"):
        validate_auth_configuration()
