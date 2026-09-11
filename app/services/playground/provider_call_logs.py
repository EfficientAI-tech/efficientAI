"""Fetch and normalize provider call logs for Vapi and Retell."""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

VAPI_API_URL = "https://api.vapi.ai"


def _fetch_bytes(url: str, *, headers: Optional[dict[str, str]] = None, timeout: int = 60) -> bytes:
    response = requests.get(url, headers=headers or {}, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.content


def _decode_log_payload(content: bytes) -> str:
    if not content:
        return ""
    if content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content).decode("utf-8")
        except OSError:
            pass
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_json_lines(text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            entries.append({"message": stripped})
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
        else:
            entries.append({"message": str(parsed)})
    return entries


def _coerce_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ms = float(value)
        if ms > 1_000_000_000_000:
            ms /= 1000.0
        return datetime.fromtimestamp(ms, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _coerce_timestamp(int(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            return text
    return str(value)


def _normalize_category(value: Any) -> str:
    text = str(value or "call").strip().lower()
    if text in {"transcriber", "stt", "speech-to-text", "asr"}:
        return "transcriber"
    if text in {"voice", "tts", "speech", "synthesizer"}:
        return "voice"
    if text in {"llm", "model", "assistant"}:
        return "llm"
    if text in {"call", "system", "pipeline"}:
        return "call"
    return text or "call"


def _normalize_level(value: Any) -> str:
    text = str(value or "info").strip().lower()
    if text in {"warn", "warning"}:
        return "warning"
    if text in {"err", "error", "fatal"}:
        return "error"
    if text in {"debug", "trace"}:
        return "debug"
    return "info"


def _summary_from_raw(raw: Dict[str, Any]) -> str:
    for key in ("message", "event", "name", "title", "type", "action", "status"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    category = raw.get("category") or raw.get("component")
    if isinstance(category, str) and category.strip():
        return category.strip()
    return "log event"


def normalize_provider_log_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    time_value = (
        raw.get("time")
        or raw.get("timestamp")
        or raw.get("createdAt")
        or raw.get("created_at")
        or raw.get("ts")
        or raw.get("date")
    )
    category = _normalize_category(
        raw.get("category")
        or raw.get("component")
        or raw.get("service")
        or raw.get("source")
        or raw.get("type")
    )
    return {
        "time": _coerce_timestamp(time_value),
        "level": _normalize_level(raw.get("level") or raw.get("severity") or raw.get("logLevel")),
        "category": category,
        "summary": _summary_from_raw(raw),
        "raw": raw,
    }


def fetch_vapi_call_logs(
    *,
    api_key: str,
    provider_call_id: str,
    call_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    content: Optional[bytes] = None
    call_data = call_data or {}
    artifact = call_data.get("artifact") if isinstance(call_data.get("artifact"), dict) else {}
    log_url = artifact.get("presignedLogUrl") or artifact.get("logUrl")
    if log_url:
        try:
            content = _fetch_bytes(str(log_url))
        except Exception as exc:
            logger.warning("[VapiLogs] Failed to fetch artifact log URL for %s: %s", provider_call_id, exc)

    if content is None:
        response = requests.get(
            f"{VAPI_API_URL}/call/{provider_call_id}/call-logs",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
            allow_redirects=True,
        )
        response.raise_for_status()
        content = response.content

    text = _decode_log_payload(content or b"")
    return [normalize_provider_log_entry(entry) for entry in _parse_json_lines(text)]


_RETELL_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+(?P<rest>.+)$"
)


def _parse_retell_log_text(text: str) -> List[Dict[str, Any]]:
    if not text.strip():
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [item if isinstance(item, dict) else {"message": str(item)} for item in parsed]
    if isinstance(parsed, dict):
        nested = parsed.get("logs") or parsed.get("entries")
        if isinstance(nested, list):
            return [item if isinstance(item, dict) else {"message": str(item)} for item in nested]
        return [parsed]

    entries: List[Dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
            entries.append(item if isinstance(item, dict) else {"message": str(item)})
            continue
        except json.JSONDecodeError:
            pass
        match = _RETELL_LINE_RE.match(stripped)
        if match:
            entries.append({"time": match.group("time"), "message": match.group("rest")})
        else:
            entries.append({"message": stripped})
    return entries


def fetch_retell_call_logs(call_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    log_url = call_data.get("public_log_url")
    if not log_url:
        return []
    content = _fetch_bytes(str(log_url))
    text = _decode_log_payload(content)
    return [normalize_provider_log_entry(entry) for entry in _parse_retell_log_text(text)]
