"""
Enterprise license validation for EfficientAI.

License keys are JWT tokens signed with RS256 (asymmetric RSA).
The private key is held by the EfficientAI team.
The public key below is used to verify licenses — it cannot be used to forge them.

Customers set the license via the EFFICIENTAI_LICENSE env var, .env, or config.yml.

JWT payload:
    {
        "features": ["voice_playground", ...],
        "org": "customer-org-name",
        "org_id": "uuid-or-null",       # optional — restricts to a specific org
        "exp": <unix-timestamp>
    }

Behaviour:
    - org_id omitted/null  → license applies to the entire deployment (self-hosted)
    - org_id set            → license only applies to that organization (multi-tenant)
"""

import os
from typing import Dict, Any, List, Optional
from uuid import UUID
from loguru import logger

_license_cache: Dict[str, Any] | None = None

ENTERPRISE_FEATURES = [
    "voice_playground",
]

# RSA public key used to verify enterprise license JWTs.
# The corresponding private key is kept offline by the EfficientAI team.
# Even though this key is visible in the source, it can only VERIFY — not sign — tokens.
EFFICIENTAI_LICENSE_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAl6UAH0skICj4UytmqzKJ
jUGj6AFEmOT+NirCEp5nNnqQV7tIPr6GidNju0IWH8/q9QJww18To9PU++BliLi4
3Tjy4fk6EgqbLIP/3ed9SMV2ChiS65QCt8nAhybJbspEjN5ViQy0Vfv9ZlVuR7Bs
nVE9nKi743y9RM6cDhEvKGlMEnHl+5EfG65rzDBbuX3F/U7QbGSi77i5SSxeW+Ac
KcRD+/5rpwuIK6C0BJgzR+zh73vPdfLxa3t3H2u2AzrFmYWxeTYjHZojVi7lp9u+
/O0Ic4T0FliF/6XblXxMmsZ+af1PQfkZtSPHeHLRNAJR7BkeMtS09u0UbJk6MU2/
UwIDAQAB
-----END PUBLIC KEY-----"""


def _get_license_token() -> str | None:
    """Resolve the license token from config.yml, .env, or environment variable."""
    try:
        from app.config import settings
        if settings.EFFICIENTAI_LICENSE:
            return settings.EFFICIENTAI_LICENSE
    except Exception:
        pass
    return os.getenv("EFFICIENTAI_LICENSE")


def _decode_license() -> Dict[str, Any]:
    """Decode and validate the license JWT using RS256. Returns the payload or empty dict."""
    token = _get_license_token()
    if not token:
        return {}

    try:
        from jose import jwt as jose_jwt, JWTError, ExpiredSignatureError

        payload = jose_jwt.decode(
            token,
            EFFICIENTAI_LICENSE_PUBLIC_KEY,
            algorithms=["RS256"],
            options={"verify_exp": True},
        )
        logger.info(
            "EfficientAI Enterprise license validated — "
            f"org={payload.get('org', 'unknown')}, "
            f"org_id={payload.get('org_id', 'all')}, "
            f"features={payload.get('features', [])}"
        )
        return payload

    except ExpiredSignatureError:
        logger.warning("EfficientAI Enterprise license has expired")
        return {}
    except (JWTError, Exception) as e:
        logger.warning(f"Invalid EfficientAI Enterprise license: {e}")
        return {}


def get_license_info() -> Dict[str, Any]:
    """Return cached license payload, decoding on first call."""
    global _license_cache
    if _license_cache is None:
        _license_cache = _decode_license()
    return _license_cache


def get_enabled_features() -> List[str]:
    """Return the list of enterprise features enabled by the current license."""
    return get_license_info().get("features", [])


def get_licensed_org_id() -> Optional[str]:
    """Return the org_id the license is scoped to, or None for deployment-wide."""
    return get_license_info().get("org_id")


def is_feature_enabled(feature: str, organization_id: Optional[UUID] = None) -> bool:
    """
    Check whether an enterprise feature is enabled.

    If the license contains an org_id, the requesting organization must match.
    If org_id is absent from the license, the feature is enabled deployment-wide.
    """
    info = get_license_info()
    if feature not in info.get("features", []):
        return False

    licensed_org = info.get("org_id")
    if licensed_org is None:
        return True

    if organization_id is None:
        return True

    return str(organization_id) == str(licensed_org)


def reset_license_cache() -> None:
    """Force re-evaluation of the license (useful after env change in tests)."""
    global _license_cache
    _license_cache = None
