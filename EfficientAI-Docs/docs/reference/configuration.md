---
id: configuration
title: Configuration
sidebar_position: 2
---

# ⚙️ Configuration

EfficientAI reads configuration from (in order of precedence):

1. **`config.yml`** — primary source of truth for both CLI and Docker runs.
2. **`.env` file / environment variables** — good for secrets you don't want
   in version control. Anything defined here overrides the YAML defaults.
3. **Process env set by your orchestrator** (`systemd`, Kubernetes, etc.).

Generate a starter file with:

```bash
eai init-config
```

---

## YAML configuration (`config.yml`)

```yaml title="config.yml"
# Application
app:
  name: "EfficientAI Voice AI Evaluation Platform"
  version: "0.1.0"
  debug: false
  # HS256 signing key for locally-issued Bearer tokens and CSRF. Change in prod.
  secret_key: "replace-me-with-a-long-random-string"

# Server
server:
  host: "0.0.0.0"
  port: 8000

# Database (required)
database:
  url: "postgresql://efficientai:password@db:5432/efficientai"

# Redis (required for websockets + Celery)
redis:
  url: "redis://redis:6379/0"

# Celery workers (required for async jobs: evaluations, TTS, optimization)
celery:
  broker_url: "redis://redis:6379/0"
  result_backend: "redis://redis:6379/0"

# File storage
storage:
  upload_dir: "/app/uploads"
  max_file_size_mb: 500
  allowed_audio_formats: ["wav", "mp3", "flac", "m4a"]

# S3 (optional, used by the Data Sources feature)
s3:
  enabled: false
  bucket_name: "your-bucket"
  region: "us-east-1"
  access_key_id: "YOUR_ACCESS_KEY_ID"
  secret_access_key: "YOUR_SECRET_ACCESS_KEY"
  endpoint_url: null         # MinIO / DO Spaces / etc.
  prefix: "audio/"

# CORS
cors:
  origins:
    - "http://localhost:3000"
    - "http://localhost:8000"

# API
api:
  prefix: "/api/v1"
  key_header: "X-API-Key"
  rate_limit_per_minute: 60

# ---------------------------------------------------------------------------
# Authentication (see the dedicated Authentication guide for full details)
# ---------------------------------------------------------------------------
auth:
  # Fixed priority order. Always include api_key + local_password for
  # OSS deployments. Add external_oidc for enterprise SSO.
  providers:
    - api_key
    - local_password
    # - external_oidc        # requires EFFICIENTAI_LICENSE feature: oidc_sso

  local_password:
    token_ttl_minutes: 720   # 12h Bearer token lifetime
    allow_signup: true       # let anonymous users create an account + org

  # Enterprise SSO: point at any OIDC-compliant IdP (Okta, Azure AD / Entra
  # ID, Google Workspace, AWS Cognito, Auth0, Ping, …). The backend
  # verifies Bearer tokens against <issuer>/.well-known/openid-configuration.
  # oidc:
  #   issuer: "https://<tenant>.okta.com"          # REQUIRED
  #   audience: "efficientai"                       # expected `aud` claim
  #   client_id: "0oa..."                           # SPA client id
  #   jwks_uri: "https://.../keys"                  # optional, derived from issuer
  #   default_org_name: "My Company"
  #   org_claim_path: ["https://efficientai.com/org"]

# Enterprise license JWT (RS256, signed by the EfficientAI team).
# Unlocks gated features: oidc_sso, mfa_enforce, audit_export,
# voice_playground, gepa_optimization, scim_provisioning, saml_sso.
# license:
#   key: "eyJhbGciOi..."
```

:::tip
Keep `secret_key`, database credentials, S3 keys, and the license JWT
**out of version control**. Put them in `.env` or your secret manager of
choice and reference them from there.
:::

---

## Environment variables (`.env`)

Anything in `config.yml` can also be set via environment variables — handy
for Docker Compose, Kubernetes, and CI. A minimal `.env`:

```bash title=".env"
# Core
SECRET_KEY=replace-me-with-a-long-random-string
DATABASE_URL=postgresql://efficientai:password@db:5432/efficientai
REDIS_URL=redis://redis:6379/0

# Postgres container (only needed if you run db via docker compose)
POSTGRES_USER=efficientai
POSTGRES_PASSWORD=password
POSTGRES_DB=efficientai

# ---- Authentication ----
# OSS self-hosted default:
AUTH_PROVIDERS=api_key,local_password
AUTH_LOCAL_TOKEN_TTL_MINUTES=720
AUTH_LOCAL_ALLOW_SIGNUP=true

# Enterprise SSO (uncomment and fill in when rolling out):
# AUTH_PROVIDERS=api_key,external_oidc
# AUTH_OIDC_ISSUER=https://<tenant>.okta.com
# AUTH_OIDC_AUDIENCE=efficientai
# AUTH_OIDC_CLIENT_ID=0oa...
# AUTH_OIDC_DEFAULT_ORG_NAME=My Company
# AUTH_OIDC_ORG_CLAIM_PATH=https://efficientai.com/org
# EFFICIENTAI_LICENSE=eyJhbGciOi...
```

---

## Reference — authentication fields

| YAML path                          | Env var                           | Default          | Description                                                               |
| ---------------------------------- | --------------------------------- | ---------------- | ------------------------------------------------------------------------- |
| `auth.providers`                   | `AUTH_PROVIDERS`                  | `[api_key]`      | Ordered list of enabled providers.                                        |
| `auth.local_password.token_ttl_minutes` | `AUTH_LOCAL_TOKEN_TTL_MINUTES` | `720`            | Bearer token lifetime for password logins.                                |
| `auth.local_password.allow_signup` | `AUTH_LOCAL_ALLOW_SIGNUP`         | `true`           | Whether `POST /auth/signup` is public.                                    |
| `auth.oidc.issuer`                 | `AUTH_OIDC_ISSUER`                | —                | Your IdP's OIDC issuer URL.                                               |
| `auth.oidc.audience`               | `AUTH_OIDC_AUDIENCE`              | —                | Expected `aud` claim on incoming tokens.                                  |
| `auth.oidc.client_id`              | `AUTH_OIDC_CLIENT_ID`             | —                | SPA client id registered in your IdP.                                     |
| `auth.oidc.jwks_uri`               | `AUTH_OIDC_JWKS_URI`              | (derived)        | Optional override; normally discovered automatically.                     |
| `auth.oidc.default_org_name`       | `AUTH_OIDC_DEFAULT_ORG_NAME`      | —                | Fallback org for first-time SSO users.                                    |
| `auth.oidc.org_claim_path`         | `AUTH_OIDC_ORG_CLAIM_PATH`        | —                | Dotted path into the JWT to locate the org name.                          |
| `license.key`                      | `EFFICIENTAI_LICENSE`             | —                | Enterprise license JWT (unlocks `oidc_sso` and other gated features).     |

See the [Authentication guide](../getting-started/authentication.md) for
the full deployment recipes and per-IdP cookbook.
