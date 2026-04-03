"""Unit tests for password helpers."""

from app.core.password import hash_password, verify_password


def test_hash_password_creates_non_plaintext_hash():
    plain = "super-secret-password"
    hashed = hash_password(plain)

    assert hashed != plain
    assert isinstance(hashed, str)
    assert hashed


def test_verify_password_accepts_valid_password():
    plain = "password-123"
    hashed = hash_password(plain)

    assert verify_password(plain, hashed) is True


def test_verify_password_rejects_invalid_password():
    hashed = hash_password("correct-password")

    assert verify_password("wrong-password", hashed) is False
