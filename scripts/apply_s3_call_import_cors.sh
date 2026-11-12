#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_CORS_TEMPLATE="${ROOT}/scripts/s3-bucket-cors-call-imports.example.json"
CONFIG_PATH="${ROOT}/config.yml"
CORS_TEMPLATE="${DEFAULT_CORS_TEMPLATE}"
BUCKET=""
REGION=""
ENDPOINT_URL=""
DRY_RUN=0
USE_CONFIG=0

usage() {
  cat <<'EOF'
Apply S3 bucket CORS for browser call-import uploads (presigned PUT from the UI).

Credentials: export before running (recommended):
  export AWS_ACCESS_KEY_ID=...
  export AWS_SECRET_ACCESS_KEY=...
  export AWS_DEFAULT_REGION=us-east-1   # optional if --region or config sets it

Usage:
  ./scripts/apply_s3_call_import_cors.sh --bucket MY_BUCKET [--region us-east-1]
  ./scripts/apply_s3_call_import_cors.sh --config config.yml

Options:
  --bucket NAME       S3 bucket (overrides config)
  --config PATH       Read s3.bucket_name, s3.region, s3.endpoint_url, cors.origins
  --cors-file PATH    CORS JSON template (default: scripts/s3-bucket-cors-call-imports.example.json)
  --region REGION     AWS region for the bucket
  --endpoint-url URL  S3-compatible endpoint (MinIO, etc.)
  --dry-run           Print planned aws command and CORS JSON; do not apply
  -h, --help          Show this help

With --config, AllowedOrigins are taken from cors.origins in that file (API + S3 stay aligned).
Without --config, edit the example JSON origins before running, or pass --config.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket) BUCKET="${2:-}"; shift 2 ;;
    --config) CONFIG_PATH="${2:-}"; USE_CONFIG=1; shift 2 ;;
    --cors-file) CORS_TEMPLATE="${2:-}"; shift 2 ;;
    --region) REGION="${2:-}"; shift 2 ;;
    --endpoint-url) ENDPOINT_URL="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ ! -f "${CORS_TEMPLATE}" ]]; then
  echo "CORS template not found: ${CORS_TEMPLATE}" >&2
  exit 1
fi

if [[ "${USE_CONFIG}" -eq 1 || ( -z "${BUCKET}" && -f "${CONFIG_PATH}" ) ]]; then
  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "Config not found: ${CONFIG_PATH}" >&2
    exit 1
  fi
  USE_CONFIG=1
fi

if [[ "${USE_CONFIG}" -eq 1 ]]; then
  mapfile -t _cfg < <(python3 - "${CONFIG_PATH}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required to read config (pip install pyyaml or use app venv)", file=sys.stderr)
    sys.exit(2)

data = yaml.safe_load(path.read_text()) or {}
s3 = data.get("s3") or {}
cors = data.get("cors") or {}
origins = cors.get("origins") or []
print(s3.get("bucket_name") or "")
print(s3.get("region") or "")
print(s3.get("endpoint_url") or "")
for o in origins:
    if o:
        print("ORIGIN:" + str(o).strip())
PY
  )
  if [[ "${#_cfg[@]}" -lt 3 ]]; then
    echo "Failed to read config: ${CONFIG_PATH}" >&2
    exit 1
  fi
  [[ -z "${BUCKET}" ]] && BUCKET="${_cfg[0]}"
  [[ -z "${REGION}" ]] && REGION="${_cfg[1]}"
  [[ -z "${ENDPOINT_URL}" || "${ENDPOINT_URL}" == "null" ]] && ENDPOINT_URL="${_cfg[2]}"
  ORIGINS=()
  for line in "${_cfg[@]:3}"; do
    [[ "${line}" == ORIGIN:* ]] && ORIGINS+=("${line#ORIGIN:}")
  done
fi

if [[ -z "${BUCKET}" || "${BUCKET}" == "your-s3-bucket-name" ]]; then
  echo "Set a real bucket: --bucket NAME or s3.bucket_name in config." >&2
  exit 1
fi

[[ -z "${REGION}" ]] && REGION="${AWS_DEFAULT_REGION:-}"
if [[ -z "${REGION}" ]]; then
  echo "Set region: --region, AWS_DEFAULT_REGION, or s3.region in config." >&2
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. Install AWS CLI v2 and retry." >&2
  exit 1
fi

CORS_JSON="$(mktemp)"
trap 'rm -f "${CORS_JSON}"' EXIT

if [[ "${USE_CONFIG}" -eq 1 && "${#ORIGINS[@]}" -gt 0 ]]; then
  python3 - "${CORS_TEMPLATE}" "${CORS_JSON}" "${ORIGINS[@]}" <<'PY'
import json
import sys
from pathlib import Path

template_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
origins = [o for o in sys.argv[3:] if o and "YOUR_APP_ORIGIN" not in o]

data = json.loads(template_path.read_text())
rules = data.get("CORSRules") or []
if not rules:
    raise SystemExit("CORS template has no CORSRules")
rules[0]["AllowedOrigins"] = origins
out_path.write_text(json.dumps(data, indent=2) + "\n")
PY
else
  cp "${CORS_TEMPLATE}" "${CORS_JSON}"
  if grep -q 'YOUR_APP_ORIGIN' "${CORS_JSON}"; then
    echo "Warning: template still contains https://YOUR_APP_ORIGIN — use --config or edit ${CORS_TEMPLATE}" >&2
  fi
fi

AWS_CMD=(aws s3api put-bucket-cors --bucket "${BUCKET}" --region "${REGION}" --cors-configuration "file://${CORS_JSON}")
if [[ -n "${ENDPOINT_URL}" && "${ENDPOINT_URL}" != "null" ]]; then
  AWS_CMD+=(--endpoint-url "${ENDPOINT_URL}")
fi

echo "Bucket:  ${BUCKET}"
echo "Region:  ${REGION}"
[[ -n "${ENDPOINT_URL}" && "${ENDPOINT_URL}" != "null" ]] && echo "Endpoint: ${ENDPOINT_URL}"
echo "CORS:"
cat "${CORS_JSON}"
echo

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "Dry run — would run: ${AWS_CMD[*]}"
  exit 0
fi

"${AWS_CMD[@]}"
echo "Applied. Verify with: aws s3api get-bucket-cors --bucket ${BUCKET} --region ${REGION}${ENDPOINT_URL:+ --endpoint-url ${ENDPOINT_URL}}"
