"""Encryption utilities for sensitive data like API keys."""

import os
from pathlib import Path
from cryptography.fernet import Fernet

# Get encryption key from environment or use a persistent file-based key
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
ENCRYPTION_KEY_FILE = Path(".encryption_key")

# Store the Fernet instance (singleton pattern)
_fernet_instance = None


def get_or_create_encryption_key() -> bytes:
    """
    Get or create a persistent encryption key.
    
    Priority:
    1. ENCRYPTION_KEY environment variable
    2. .encryption_key file (created if doesn't exist)
    3. Generate new key and save to file
    
    Returns:
        Fernet key as bytes
    """
    # First, try environment variable
    if ENCRYPTION_KEY:
        try:
            key_bytes = ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY
            # Validate it's a valid Fernet key
            Fernet(key_bytes)
            return key_bytes
        except Exception:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Invalid ENCRYPTION_KEY from environment, falling back to file-based key")
    
    # Second, try to read from file
    if ENCRYPTION_KEY_FILE.exists():
        try:
            key = ENCRYPTION_KEY_FILE.read_text().strip()
            key_bytes = key.encode() if isinstance(key, str) else key
            # Validate it's a valid Fernet key
            Fernet(key_bytes)
            return key_bytes
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to read encryption key from file: {e}, generating new key")
    
    # Third, generate new key and save to file
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Generating new encryption key and saving to .encryption_key file")
    
    key = Fernet.generate_key()
    
    # Save to file with restricted permissions (readable only by owner)
    try:
        ENCRYPTION_KEY_FILE.write_bytes(key)
        # Set file permissions to 600 (read/write for owner only)
        os.chmod(ENCRYPTION_KEY_FILE, 0o600)
        logger.info(f"Encryption key saved to {ENCRYPTION_KEY_FILE.absolute()}")
        
        # Warn if this is the first time
        if not ENCRYPTION_KEY:
            import warnings
            warnings.warn(
                f"Using file-based encryption key stored in {ENCRYPTION_KEY_FILE.absolute()}. "
                f"For production, set ENCRYPTION_KEY environment variable for better security.",
                UserWarning
            )
    except Exception as e:
        logger.error(f"Failed to save encryption key to file: {e}")
        # Still return the key so the app can function, but warn
        import warnings
        warnings.warn(
            f"Could not save encryption key to file. Key will be regenerated on next restart. "
            f"Set ENCRYPTION_KEY environment variable for persistence.",
            UserWarning
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
    encrypted = f.encrypt(api_key.encode('utf-8'))
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
        # Try to decrypt (assumes it's encrypted)
        decrypted = f.decrypt(encrypted_api_key.encode('utf-8'))
        return decrypted.decode('utf-8')
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
            return encrypted_api_key

