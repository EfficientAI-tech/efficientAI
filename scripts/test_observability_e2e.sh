#!/usr/bin/env bash
# Quick smoke test for Product Observability APIs.
#
# Usage:
#   export EFFICIENTAI_API_KEY="your-key-from-settings"
#   ./scripts/test_observability_e2e.sh
#
# Optional:
#   BASE_URL=http://localhost:8000 ./scripts/test_observability_e2e.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1/observability}"
API_KEY="${EFFICIENTAI_API_KEY:-}"

if [[ -z "$API_KEY" ]]; then
  echo "Set EFFICIENTAI_API_KEY (Settings → API Keys in the UI)." >&2
  exit 1
fi

TRACE_ID="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
)"
CALL_ID="test-$(date +%s)"

echo "== Health =="
curl -sf "$BASE_URL/health" | head -c 120
echo ""

echo "== Webhook ingest (flat payload + trace_id) =="
INGEST=$(curl -s -w "\nHTTP:%{http_code}" -X POST \
  "$BASE_URL${API_PREFIX}/calls/webhook/$API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"id\": \"$CALL_ID\",
    \"provider_platform\": \"external\",
    \"startedAt\": \"2026-08-07T09:00:00.000Z\",
    \"endedAt\": \"2026-08-07T09:01:30.000Z\",
    \"trace_id\": \"$TRACE_ID\",
    \"messages\": [{\"role\": \"user\", \"content\": \"hello\"}, {\"role\": \"bot\", \"content\": \"hi there\"}]
  }")
HTTP_CODE="${INGEST##*HTTP:}"
BODY="${INGEST%HTTP:*}"
echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
if [[ "$HTTP_CODE" != "201" ]]; then
  echo "Ingest failed (HTTP $HTTP_CODE)" >&2
  exit 1
fi

CALL_SHORT_ID="$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('call_short_id',''))")"
if [[ -z "$CALL_SHORT_ID" ]]; then
  echo "Could not parse call_short_id from ingest response" >&2
  exit 1
fi

echo ""
echo "== List calls =="
curl -sf "$BASE_URL${API_PREFIX}/calls" -H "X-API-Key: $API_KEY" | python3 -m json.tool | head -40

echo ""
echo "== Summary =="
SUMMARY_JSON="$(curl -sf "$BASE_URL${API_PREFIX}/calls/summary" -H "X-API-Key: $API_KEY")"
echo "$SUMMARY_JSON" | python3 -m json.tool
python3 - <<'PY' "$SUMMARY_JSON"
import json
import sys

payload = json.loads(sys.argv[1])
required = {"total_calls", "total_minutes", "avg_latency_ms"}
missing = sorted(required - payload.keys())
if missing:
    raise SystemExit(f"Summary payload missing fields: {', '.join(missing)}")
PY

echo ""
echo "== Trace fetch (expect 502 if Tempo/cloud has no spans for this trace_id) =="
TRACE_RESP=$(curl -s -w "\nHTTP:%{http_code}" \
  "$BASE_URL${API_PREFIX}/calls/$CALL_SHORT_ID/trace" \
  -H "X-API-Key: $API_KEY")
TRACE_HTTP="${TRACE_RESP##*HTTP:}"
TRACE_BODY="${TRACE_RESP%HTTP:*}"
if [[ "$TRACE_HTTP" == "200" ]]; then
  echo "$TRACE_BODY" | python3 -m json.tool | head -60
else
  echo "Trace query returned HTTP $TRACE_HTTP (normal for webhook-only test without live spans)"
  echo "$TRACE_BODY"
fi

echo ""
echo "== Retell synthetic trace smoke =="
RETELL_CALL_ID="retell-smoke-$(date +%s)"
RETELL_INGEST=$(curl -s -w "\nHTTP:%{http_code}" -X POST \
  "$BASE_URL${API_PREFIX}/calls/webhook/retell/$API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"event\": \"call_ended\",
    \"call\": {
      \"call_id\": \"$RETELL_CALL_ID\",
      \"call_status\": \"ended\",
      \"start_timestamp\": 1714423232000,
      \"end_timestamp\": 1714423257000,
      \"transcript_object\": [
        {\"role\": \"user\", \"content\": \"hello\", \"words\": [{\"start\": 0.4, \"end\": 0.9}]},
        {\"role\": \"agent\", \"content\": \"hi there\", \"words\": [{\"start\": 1.2, \"end\": 2.0}]}
      ],
      \"latency\": {\"asr\": {\"p50\": 120}, \"llm\": {\"p50\": 350}, \"tts\": {\"p50\": 220}}
    }
  }")
RETELL_HTTP="${RETELL_INGEST##*HTTP:}"
RETELL_BODY="${RETELL_INGEST%HTTP:*}"
if [[ "$RETELL_HTTP" != "201" ]]; then
  echo "Retell ingest failed (HTTP $RETELL_HTTP)" >&2
  echo "$RETELL_BODY"
  exit 1
fi
RETELL_SHORT_ID="$(echo "$RETELL_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('call_short_id',''))")"
RETELL_TRACE=$(curl -s -w "\nHTTP:%{http_code}" \
  "$BASE_URL${API_PREFIX}/calls/$RETELL_SHORT_ID/trace" \
  -H "X-API-Key: $API_KEY")
RETELL_TRACE_HTTP="${RETELL_TRACE##*HTTP:}"
RETELL_TRACE_BODY="${RETELL_TRACE%HTTP:*}"
if [[ "$RETELL_TRACE_HTTP" != "200" ]]; then
  echo "Retell synthetic trace fetch failed (HTTP $RETELL_TRACE_HTTP)" >&2
  echo "$RETELL_TRACE_BODY"
  exit 1
fi
python3 - <<'PY' "$RETELL_TRACE_BODY"
import json, sys
payload = json.loads(sys.argv[1])
assert payload.get("trace_source") == "retell_synthetic", payload
assert any(span.get("name") == "stt" for span in payload.get("spans", [])), payload
PY

echo ""
echo "== Vapi synthetic trace smoke =="
VAPI_CALL_ID="vapi-smoke-$(date +%s)"
VAPI_INGEST=$(curl -s -w "\nHTTP:%{http_code}" -X POST \
  "$BASE_URL${API_PREFIX}/calls/webhook/vapi/$API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"id\": \"$VAPI_CALL_ID\",
    \"status\": \"ended\",
    \"startedAt\": \"2026-08-07T09:00:00.000Z\",
    \"endedAt\": \"2026-08-07T09:00:10.000Z\",
    \"messages\": [
      {\"role\": \"user\", \"message\": \"hello\", \"secondsFromStart\": 0.5, \"duration\": 900},
      {\"role\": \"assistant\", \"message\": \"hi there\", \"secondsFromStart\": 1.6, \"duration\": 1200}
    ],
    \"artifact\": {
      \"performanceMetrics\": {
        \"modelLatencyAverage\": 320,
        \"voiceLatencyAverage\": 480,
        \"transcriberLatencyAverage\": 210,
        \"endpointingLatencyAverage\": 140
      }
    }
  }")
VAPI_HTTP="${VAPI_INGEST##*HTTP:}"
VAPI_BODY="${VAPI_INGEST%HTTP:*}"
if [[ "$VAPI_HTTP" != "201" ]]; then
  echo "Vapi ingest failed (HTTP $VAPI_HTTP)" >&2
  echo "$VAPI_BODY"
  exit 1
fi
VAPI_SHORT_ID="$(echo "$VAPI_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('call_short_id',''))")"
VAPI_TRACE=$(curl -s -w "\nHTTP:%{http_code}" \
  "$BASE_URL${API_PREFIX}/calls/$VAPI_SHORT_ID/trace" \
  -H "X-API-Key: $API_KEY")
VAPI_TRACE_HTTP="${VAPI_TRACE##*HTTP:}"
VAPI_TRACE_BODY="${VAPI_TRACE%HTTP:*}"
if [[ "$VAPI_TRACE_HTTP" != "200" ]]; then
  echo "Vapi synthetic trace fetch failed (HTTP $VAPI_TRACE_HTTP)" >&2
  echo "$VAPI_TRACE_BODY"
  exit 1
fi
python3 - <<'PY' "$VAPI_TRACE_BODY"
import json, sys
payload = json.loads(sys.argv[1])
assert payload.get("trace_source") == "vapi_synthetic", payload
assert any(span.get("name") == "llm" for span in payload.get("spans", [])), payload
PY

echo ""
echo "Done."
echo "  Call short id: $CALL_SHORT_ID"
echo "  Trace id:      $TRACE_ID"
echo "  UI:            $BASE_URL/observability/calls/$CALL_SHORT_ID"
