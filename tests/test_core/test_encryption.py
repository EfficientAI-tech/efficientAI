"""Unit tests for encryption utilities."""

from cryptography.fernet import Fernet
import pytest

from app.core import encryption


@pytest.fixture
def isolated_fernet(monkeypatch):
    """Use a deterministic in-memory Fernet instance for each test."""
    key = Fernet.generate_key()
    fernet = Fernet(key)
    monkeypatch.setattr(encryption, "_fernet_instance", None)
    monkeypatch.setattr(encryption, "get_fernet", lambda: fernet)
    return fernet


def test_encrypt_decrypt_round_trip(isolated_fernet):
    original = "sk-test-key-abc123"

    encrypted = encryption.encrypt_api_key(original)
    decrypted = encryption.decrypt_api_key(encrypted)

    assert encrypted != original
    assert decrypted == original


def test_decrypt_plain_text_key_falls_back_for_backward_compatibility(isolated_fernet):
    plain = "sk-plain-text-key"

    assert encryption.decrypt_api_key(plain) == plain


def test_decrypt_empty_key_raises_value_error(isolated_fernet):
    with pytest.raises(ValueError, match="API key is empty"):
        encryption.decrypt_api_key("")
