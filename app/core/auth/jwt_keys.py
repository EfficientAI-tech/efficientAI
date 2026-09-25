"""RSA key material for app-issued session JWTs (RS256)."""

from __future__ import annotations

import logging
from typing import Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose.constants import ALGORITHMS

from app.config import settings

logger = logging.getLogger(__name__)

SESSION_JWT_ALGORITHM = ALGORITHMS.RS256

_signing_key_pem: bytes | None = None
_verification_key_pem: bytes | None = None
_ephemeral_generated: bool = False


def _normalize_pem(value: str | None) -> bytes | None:
    raw = (value or "").strip()
    if not raw:
        return None
    return raw.encode("utf-8")


def _generate_ephemeral_rsa_pair() -> Tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def ensure_session_jwt_keys() -> None:
    """Load or (debug-only) generate RSA keys for signing and verifying session JWTs."""
    global _signing_key_pem, _verification_key_pem, _ephemeral_generated

    if _signing_key_pem is not None and _verification_key_pem is not None:
        return

    private_pem = _normalize_pem(settings.AUTH_JWT_PRIVATE_KEY_PEM)
    public_pem = _normalize_pem(settings.AUTH_JWT_PUBLIC_KEY_PEM)

    if private_pem and public_pem:
        _signing_key_pem = private_pem
        _verification_key_pem = public_pem
        return

    if settings.DEBUG:
        private_pem, public_pem = _generate_ephemeral_rsa_pair()
        _signing_key_pem = private_pem
        _verification_key_pem = public_pem
        _ephemeral_generated = True
        logger.warning(
            "AUTH_JWT_* PEM not set; using ephemeral RS256 keys (DEBUG only). "
            "Set auth.jwt_private_key_pem / auth.jwt_public_key_pem for production."
        )
        return

    raise RuntimeError(
        "AUTH_JWT_PRIVATE_KEY_PEM and AUTH_JWT_PUBLIC_KEY_PEM must be set in non-debug "
        "deployments (config.yml auth.jwt_private_key_pem / auth.jwt_public_key_pem)."
    )


def session_jwt_signing_key() -> bytes:
    ensure_session_jwt_keys()
    assert _signing_key_pem is not None
    return _signing_key_pem


def session_jwt_verification_key() -> bytes:
    ensure_session_jwt_keys()
    assert _verification_key_pem is not None
    return _verification_key_pem


def validate_session_jwt_key_configuration() -> None:
    """Fail fast when production requires explicit RSA key pair."""
    if settings.DEBUG:
        ensure_session_jwt_keys()
        return
    if not (settings.AUTH_JWT_PRIVATE_KEY_PEM or "").strip():
        raise RuntimeError("AUTH_JWT_PRIVATE_KEY_PEM is required when DEBUG=false.")
    if not (settings.AUTH_JWT_PUBLIC_KEY_PEM or "").strip():
        raise RuntimeError("AUTH_JWT_PUBLIC_KEY_PEM is required when DEBUG=false.")
    ensure_session_jwt_keys()
