#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ELEVENLABS_API_KEY=... ./scripts/test_elevenlabs_trace_e2e.sh conv_xxx
#
# This helper validates that ElevenLabs OTLP spans are present
# for a completed conversation.

if [[ $# -lt 1 ]]; then
  echo "Usage: ELEVENLABS_API_KEY=... $0 <conversation_id>"
  exit 1
fi

if [[ -z "${ELEVENLABS_API_KEY:-}" ]]; then
  echo "ELEVENLABS_API_KEY is required"
  exit 1
fi

CONV_ID="$1"
BASE_URL="${ELEVENLABS_BASE_URL:-https://api.elevenlabs.io}"

echo "Fetching conversation OTLP payload for: ${CONV_ID}"

RAW_JSON="$(mktemp)"
curl -sS "${BASE_URL}/v1/convai/conversations/${CONV_ID}?format=opentelemetry" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" > "${RAW_JSON}"

echo "Conversation status:"
jq -r '.status' "${RAW_JSON}"

echo "Span names:"
jq -r '.otlp_traces.resourceSpans[]?.scopeSpans[]?.spans[]?.name' "${RAW_JSON}" | sort -u

USER_TURNS="$(jq '[.otlp_traces.resourceSpans[]?.scopeSpans[]?.spans[]? | select(.name=="elevenlabs.recv.user_transcript")] | length' "${RAW_JSON}")"
AGENT_TURNS="$(jq '[.otlp_traces.resourceSpans[]?.scopeSpans[]?.spans[]? | select(.name=="elevenlabs.recv.agent_response")] | length' "${RAW_JSON}")"

echo "User turn spans:  ${USER_TURNS}"
echo "Agent turn spans: ${AGENT_TURNS}"

if [[ "${USER_TURNS}" -lt 1 || "${AGENT_TURNS}" -lt 1 ]]; then
  echo "Missing expected turn spans."
  exit 2
fi

echo "OTLP trace payload looks valid."
