"""Password hashing and policy utilities."""

import re

import bcrypt

_PASSWORD_MIN_LENGTH = 8
_PASSWORD_MAX_LENGTH = 32
_HAS_UPPER = re.compile(r"[A-Z]")
_HAS_LOWER = re.compile(r"[a-z]")
_HAS_DIGIT = re.compile(r"\d")
_HAS_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def validate_password_strength(password: str) -> None:
    """
    Enforce password complexity rules.

    Raises:
        ValueError: When the password does not meet policy requirements.
    """
    if len(password) < _PASSWORD_MIN_LENGTH or len(password) > _PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Password must be between {_PASSWORD_MIN_LENGTH} and {_PASSWORD_MAX_LENGTH} characters."
        )
    if not _HAS_UPPER.search(password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not _HAS_LOWER.search(password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not _HAS_DIGIT.search(password):
        raise ValueError("Password must contain at least one digit.")
    if not _HAS_SPECIAL.search(password):
        raise ValueError("Password must contain at least one special character.")


def hash_password(password: str) -> str:
    """
    Hash a password.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password

    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False

