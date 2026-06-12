"""Tests for OIDC configuration validation and JWT audience enforcement."""

import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import base64url_encode

from app.config import settings, validate_auth_configuration
from app.core.auth.oidc_common import reset_jwks_cache, verify_jwt
from app.core.auth.providers import AuthError


def _build_rsa_jwks(private_key, kid: str = "test-kid") -> list[dict]:
    public_numbers = private_key.public_key().public_numbers()
    e = base64url_encode(public_numbers.e.to_bytes(3, "big")).decode()
    n = base64url_encode(
        public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    ).decode()
    return [
        {
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
            "n": n,
            "e": e,
        }
    ]


def _private_key_pem(private_key) -> str:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _mint_token(private_key, *, aud: str, iss: str = "https://idp.example.com") -> str:
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": iss,
            "aud": aud,
            "exp": int(time.time()) + 3600,
        },
        _private_key_pem(private_key),
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )


def test_validate_auth_configuration_allows_api_key_only(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key"])
    validate_auth_configuration()


def test_validate_auth_configuration_skips_oidc_without_license(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "external_oidc"])
    monkeypatch.setattr(settings, "AUTH_OIDC_ISSUER", None)
    monkeypatch.setattr(settings, "AUTH_OIDC_AUDIENCE", None)
    monkeypatch.setattr("app.core.license.has_auth_feature", lambda _f: False)
    validate_auth_configuration()


def test_validate_auth_configuration_requires_audience_for_external_oidc(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["external_oidc"])
    monkeypatch.setattr(settings, "AUTH_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setattr(settings, "AUTH_OIDC_AUDIENCE", None)
    monkeypatch.setattr("app.core.license.has_auth_feature", lambda f: f == "oidc_sso")
    with pytest.raises(RuntimeError, match="AUTH_OIDC_AUDIENCE"):
        validate_auth_configuration()


def test_verify_jwt_rejects_missing_audience(monkeypatch):
    reset_jwks_cache()
    with pytest.raises(AuthError, match="OIDC audience is not configured"):
        verify_jwt(
            "token",
            jwks_uri="https://idp.example.com/jwks",
            issuer="https://idp.example.com",
            audience=None,
        )


def test_verify_jwt_rejects_wrong_audience(monkeypatch):
    reset_jwks_cache()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_uri = "https://idp.example.com/jwks"
    monkeypatch.setattr(
        "app.core.auth.oidc_common.fetch_jwks",
        lambda _uri: _build_rsa_jwks(private_key),
    )
    token = _mint_token(private_key, aud="wrong-app")

    with pytest.raises(AuthError):
        verify_jwt(
            token,
            jwks_uri=jwks_uri,
            issuer="https://idp.example.com",
            audience="efficientai",
        )


def test_verify_jwt_accepts_matching_audience(monkeypatch):
    reset_jwks_cache()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_uri = "https://idp.example.com/jwks"
    monkeypatch.setattr(
        "app.core.auth.oidc_common.fetch_jwks",
        lambda _uri: _build_rsa_jwks(private_key),
    )
    token = _mint_token(private_key, aud="efficientai")

    claims = verify_jwt(
        token,
        jwks_uri=jwks_uri,
        issuer="https://idp.example.com",
        audience="efficientai",
    )
    assert claims["aud"] == "efficientai"
