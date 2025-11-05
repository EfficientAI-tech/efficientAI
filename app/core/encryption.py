"""Encryption utilities for sensitive data like API keys."""

import os
from cryptography.fernet import Fernet

# Get encryption key from environment or use a default (for development only)
# In production, this should be a secure environment variable with a Fernet key
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Store the Fernet instance (singleton pattern)
_fernet_instance = None


def get_fernet() -> Fernet:
    """
    Get or create Fernet encryption instance.
    
    Returns:
        Fernet instance for encryption/decryption
    """
    global _fernet_instance
    
    if _fernet_instance is not None:
        return _fernet_instance
    
    if ENCRYPTION_KEY:
        # Use provided key from environment
        try:
            key_bytes = ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY
            _fernet_instance = Fernet(key_bytes)
            return _fernet_instance
        except Exception:
            # If key is invalid, fall through to generate new one
            pass
    
    # Generate a new key for development (DO NOT use in production!)
    # In production, set ENCRYPTION_KEY environment variable with a persistent key
    key = Fernet.generate_key()
    _fernet_instance = Fernet(key)
    
    # Warn about using default key (only in development)
    if not ENCRYPTION_KEY:
        import warnings
        warnings.warn(
            "Using auto-generated encryption key. Set ENCRYPTION_KEY environment variable for production!",
            UserWarning
        )
    
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
    
    Args:
        encrypted_api_key: Encrypted API key (base64 encoded)
        
    Returns:
        Plain text API key
    """
    f = get_fernet()
    decrypted = f.decrypt(encrypted_api_key.encode('utf-8'))
    return decrypted.decode('utf-8')

