"""Unit tests for password helpers."""

import pytest

from app.core.password import hash_password, validate_password_strength, verify_password

VALID_PASSWORD = "TestPass1!"


def test_hash_password_creates_non_plaintext_hash():
    plain = VALID_PASSWORD
    hashed = hash_password(plain)

    assert hashed != plain
    assert isinstance(hashed, str)
    assert hashed


def test_verify_password_accepts_valid_password():
    plain = VALID_PASSWORD
    hashed = hash_password(plain)

    assert verify_password(plain, hashed) is True


def test_verify_password_rejects_invalid_password():
    hashed = hash_password(VALID_PASSWORD)

    assert verify_password("WrongPass1!", hashed) is False


def test_validate_password_strength_accepts_valid_password():
    validate_password_strength(VALID_PASSWORD)


@pytest.mark.parametrize(
    "password,message",
    [
        ("short1!", "between 8 and 32"),
        ("a" * 33 + "A1!", "between 8 and 32"),
        ("alllowercase1!", "uppercase"),
        ("ALLUPPERCASE1!", "lowercase"),
        ("NoDigitsHere!", "digit"),
        ("NoSpecialChar1", "special character"),
    ],
)
def test_validate_password_strength_rejects_invalid_password(password, message):
    with pytest.raises(ValueError, match=message):
        validate_password_strength(password)
