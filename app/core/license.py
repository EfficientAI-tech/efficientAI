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
_license_token_cached: str | None = None

FEATURE_CATALOG: Dict[str, Dict[str, str]] = {
    "voice_playground": {
        "title": "Voice Playground",
        "description": "A/B test TTS providers with blind tests and quality analytics.",
        "category": "playground",
    },
    "call_imports": {
        "title": "Call Imports",
        "description": "Bulk-import production call recordings via CSV and run batch evaluations on them.",
        "category": "evaluation",
    },
    "evaluation_clustering": {
        "title": "Evaluation Failure Clustering",
        "description": "Cluster failed evaluation runs from LLM rationales to surface recurring failure patterns.",
        "category": "evaluation",
    },
    "alerts": {
        "title": "Alerting",
        "description": "Threshold-based alerts on evaluation metrics with email and webhook notifications.",
        "category": "monitoring",
    },
    "metric_studio": {
        "title": "Metric Studio",
        "description": "Batch ad-hoc metric scoring runs against evaluation results and call imports.",
        "category": "evaluation",
    },
    "db_sharding": {
        "title": "Call Import DB Sharding",
        "description": "Horizontally shard call-import row storage across multiple database nodes.",
        "category": "operations",
    },
    "llm_gateway": {
        "title": "LLM Gateway",
        "description": "Route batch LLM workloads through Bifrost or LiteLLM Proxy from Integrations.",
        "category": "integrations",
    },
    "enterprise_platform": {
        "title": "Enterprise Platform",
        "description": "Unlocks default enterprise offerings (alerts, metric studio, sharding, gateway).",
        "category": "platform",
    },
    "gepa_optimization": {
        "title": "Prompt Optimization",
        "description": "Self-improving voice agents via reflective prompt evolution (GEPA). Open source — catalog entry kept for legacy JWT compatibility.",
        "category": "optimization",
    },
    # --- Authentication features (gate pluggable auth providers) ---
    "oidc_sso": {
        "title": "Enterprise SSO (OIDC)",
        "description": "Bring your own identity provider: Okta, Azure AD, Google Workspace, AWS Cognito, Auth0, Ping, etc.",
        "category": "auth",
    },
    "saml_sso": {
        "title": "SAML SSO",
        "description": "Sign in via SAML 2.0 assertions from an enterprise IdP.",
        "category": "auth",
    },
    "scim_provisioning": {
        "title": "SCIM User Provisioning",
        "description": "Automated user and group sync from your IdP over SCIM 2.0.",
        "category": "auth",
    },
    "mfa_enforce": {
        "title": "Enforced MFA",
        "description": "Require multi-factor authentication for all human sign-ins.",
        "category": "auth",
    },
    "audit_export": {
        "title": "Audit Log Export",
        "description": "Stream authentication and access events to SIEM via S3 or webhook.",
        "category": "auth",
    },
}

# Auth-category features (kept in sync with FEATURE_CATALOG). Used by the
# pluggable auth providers to short-circuit with a helpful error message.
AUTH_FEATURES: List[str] = [
    "oidc_sso",
    "saml_sso",
    "scim_provisioning",
    "mfa_enforce",
    "audit_export",
]

# Backward-compatible export used by existing API response shape.
ENTERPRISE_FEATURES = list(FEATURE_CATALOG.keys())

# Included with any valid enterprise contract (JWT with at least one catalog feature).
DEFAULT_ENTERPRISE_OFFERINGS: List[str] = [
    "alerts",
    "metric_studio",
    "db_sharding",
    "llm_gateway",
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
    global _license_cache, _license_token_cached
    current_token = _get_license_token()
    if current_token != _license_token_cached:
        _license_cache = None
        _license_token_cached = current_token
    if _license_cache is None:
        _license_cache = _decode_license()
    return _license_cache


def get_enabled_features() -> List[str]:
    """Return the list of enterprise features enabled by the current license."""
    licensed_features = get_license_info().get("features", [])
    if not isinstance(licensed_features, list):
        return []
    # Keep only known feature IDs to avoid accidental entitlement typos.
    return [f for f in licensed_features if f in FEATURE_CATALOG]


def get_feature_catalog() -> Dict[str, Dict[str, str]]:
    """Return metadata for all enterprise features."""
    # Return shallow copies to avoid callers mutating global state.
    return {feature: meta.copy() for feature, meta in FEATURE_CATALOG.items()}


def get_licensed_org_id() -> Optional[str]:
    """Return the org_id the license is scoped to, or None for deployment-wide."""
    return get_license_info().get("org_id")


def has_valid_license(organization_id: Optional[UUID] = None) -> bool:
    """True when EFFICIENTAI_LICENSE is a valid, non-expired JWT for this org."""
    info = get_license_info()
    if not info:
        return False

    licensed_org = info.get("org_id")
    if licensed_org is None:
        return True

    if organization_id is None:
        return False

    return str(organization_id) == str(licensed_org)


def _license_applies_to_org(organization_id: Optional[UUID] = None) -> bool:
    """True when a valid JWT is present and applies to the given organization."""
    if not get_enabled_features():
        return False

    return has_valid_license(organization_id)


def is_feature_enabled(feature: str, organization_id: Optional[UUID] = None) -> bool:
    """
    Check whether an enterprise feature is enabled.

    If the license contains an org_id, the requesting organization must match.
    If org_id is absent from the license, the feature is enabled deployment-wide.

    Features in ``DEFAULT_ENTERPRISE_OFFERINGS`` are enabled for any org with
    a valid enterprise entitlement, even when omitted from the JWT feature list.
    """
    if feature in get_enabled_features():
        return _license_applies_to_org(organization_id)

    if feature in DEFAULT_ENTERPRISE_OFFERINGS and _license_applies_to_org(
        organization_id
    ):
        return True

    return False


def get_features_enabled_for_org(organization_id: Optional[UUID] = None) -> List[str]:
    """Return all feature IDs enabled for an organization (JWT + default offerings)."""
    enabled: List[str] = []
    seen: set[str] = set()
    for feature_id in FEATURE_CATALOG:
        if is_feature_enabled(feature_id, organization_id):
            if feature_id not in seen:
                enabled.append(feature_id)
                seen.add(feature_id)
    return enabled


def has_auth_feature(feature: str) -> bool:
    """
    Check whether an auth-category enterprise feature is enabled.

    Unlike `is_feature_enabled`, this is deployment-scoped: auth features
    apply before we know which organization the caller belongs to (we're
    still in the middle of figuring that out!). A license scoped to a
    specific org is therefore treated as deployment-wide for auth.
    """
    if feature not in AUTH_FEATURES:
        return False
    return feature in get_enabled_features()


def reset_license_cache() -> None:
    """Force re-evaluation of the license (useful after env change in tests)."""
    global _license_cache, _license_token_cached
    _license_cache = None
    _license_token_cached = None
