"""Encryption utilities for sensitive data like API keys."""

import logging
import os
from pathlib import Path
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Get encryption key from environment or use a persistent file-based key
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Key file search paths (first match wins, new keys are written to the first
# writable path).  .data/ is a directory mount that works reliably in both
# CLI and Docker, while .encryption_key is the legacy single-file location.
_KEY_FILE_PATHS = [
    Path(".data/.encryption_key"),
    Path(".encryption_key"),
]

# Store the Fernet instance (singleton pattern)
_fernet_instance = None


def _read_key_from_file(path: Path) -> bytes | None:
    """Try to read and validate a Fernet key from *path*. Returns None on failure."""
    if not path.is_file():
        return None
    try:
        key_bytes = path.read_text().strip().encode()
        Fernet(key_bytes)
        return key_bytes
    except Exception as e:
        logger.warning(f"Invalid encryption key in {path}: {e}")
        return None


def _write_key_to_file(key: bytes) -> Path | None:
    """Write *key* to the first writable candidate path. Returns the path used, or None."""
    for path in _KEY_FILE_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key)
            os.chmod(path, 0o600)
            logger.info(f"Encryption key saved to {path.absolute()}")
            return path
        except Exception:
            continue
    return None


def get_or_create_encryption_key() -> bytes:
    """
    Get or create a persistent encryption key.

    Priority:
      1. ENCRYPTION_KEY environment variable
      2. First valid key file found in _KEY_FILE_PATHS
      3. Generate new key and save to the first writable path
    """
    if ENCRYPTION_KEY:
        try:
            key_bytes = ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY
            Fernet(key_bytes)
            return key_bytes
        except Exception:
            logger.warning("Invalid ENCRYPTION_KEY from environment, falling back to file-based key")

    for path in _KEY_FILE_PATHS:
        key_bytes = _read_key_from_file(path)
        if key_bytes:
            return key_bytes

    logger.info("No existing encryption key found, generating a new one")
    key = Fernet.generate_key()

    saved_path = _write_key_to_file(key)
    if saved_path:
        import warnings
        warnings.warn(
            f"Using file-based encryption key stored in {saved_path.absolute()}. "
            f"For production, set ENCRYPTION_KEY environment variable for better security.",
            UserWarning,
        )
    else:
        logger.error("Failed to save encryption key to any file path")
        import warnings
        warnings.warn(
            "Could not save encryption key to file. Key will be regenerated on next restart. "
            "Set ENCRYPTION_KEY environment variable for persistence.",
            UserWarning,
        )

    return key


def get_fernet() -> Fernet:
    """
    Get or create Fernet encryption instance with persistent key.
    
    Returns:
        Fernet instance for encryption/decryption
    """
    global _fernet_instance
    
    if _fernet_instance is not None:
        return _fernet_instance
    
    key = get_or_create_encryption_key()
    _fernet_instance = Fernet(key)
    
    return _fernet_instance


def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt an API key for storage.
    
    Args:
        api_key: Plain text API key (can be any length)
        
    Returns:
        Encrypted API key (base64 encoded)
    """
    f = get_fernet()
    encrypted = f.encrypt(api_key.strip().encode('utf-8'))
    return encrypted.decode('utf-8')


def decrypt_api_key(encrypted_api_key: str) -> str:
    """
    Decrypt an API key for use.
    Handles both encrypted and plain text keys for backward compatibility.
    
    Args:
        encrypted_api_key: Encrypted API key (base64 encoded) or plain text key
        
    Returns:
        Plain text API key
        
    Raises:
        ValueError: If the key is empty or decryption fails and key appears encrypted
        RuntimeError: If decryption fails due to wrong encryption key
    """
    if not encrypted_api_key:
        raise ValueError("API key is empty")
    
    # Check if the key looks encrypted (Fernet tokens start with gAAAAA)
    # OpenAI API keys typically start with 'sk-' and are not base64-encoded Fernet tokens
    looks_encrypted = encrypted_api_key.startswith('gAAAAA') or (
        len(encrypted_api_key) > 100 and 
        not encrypted_api_key.startswith('sk-') and 
        not encrypted_api_key.startswith('AIza') and
        not encrypted_api_key.startswith('x-')
    )
    
    f = get_fernet()
    try:
        decrypted = f.decrypt(encrypted_api_key.encode('utf-8'))
        return decrypted.decode('utf-8').strip()
    except Exception as e:
        # If decryption fails
        import logging
        logger = logging.getLogger(__name__)
        
        if looks_encrypted:
            # Key appears encrypted but decryption failed - likely wrong encryption key
            logger.error(
                f"Failed to decrypt API key: Key appears encrypted but decryption failed. "
                f"This usually means ENCRYPTION_KEY environment variable changed or is missing. "
                f"Original error: {str(e)}"
            )
            raise RuntimeError(
                "API key decryption failed. The encryption key may have changed. "
                "Please re-enter your API key in the AI Providers settings, or set a persistent "
                "ENCRYPTION_KEY environment variable."
            )
        else:
            # Key doesn't look encrypted, assume it's plain text (backward compatibility)
            logger.warning("API key decryption failed, assuming plain text (backward compatibility)")
            return encrypted_api_key.strip()

