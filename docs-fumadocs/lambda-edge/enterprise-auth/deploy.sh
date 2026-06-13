#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
ZIP_PATH="${DIST_DIR}/enterprise-auth.zip"
FUNCTION_NAME="${DOCS_AUTH_LAMBDA_NAME:-efficientai-docs-enterprise-auth}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [[ -z "${DOCS_ENTERPRISE_PASSWORD:-}" ]]; then
  echo "Set DOCS_ENTERPRISE_PASSWORD before building/deploying." >&2
  exit 1
fi

node "${ROOT_DIR}/build.mjs"

rm -f "${ZIP_PATH}"
(cd "${DIST_DIR}" && zip -q "${ZIP_PATH}" index.js)

if [[ "${1:-}" == "--build-only" ]]; then
  echo "Built ${ZIP_PATH}"
  exit 0
fi

aws lambda update-function-code \
  --region "${AWS_REGION}" \
  --function-name "${FUNCTION_NAME}" \
  --zip-file "fileb://${ZIP_PATH}"

NEW_VERSION="$(aws lambda publish-version \
  --region "${AWS_REGION}" \
  --function-name "${FUNCTION_NAME}" \
  --query 'Version' \
  --output text)"

echo "Published Lambda version: ${NEW_VERSION}"
echo "Associate this version with your CloudFront /docs/enterprise/* cache behavior (viewer-request)."
