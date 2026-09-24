"""HTTP chat turn client for customer-hosted production agents."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urljoin

import httpx

DEFAULT_TIMEOUT_SECS = 60.0


def _openai_style_messages(transcript: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in transcript:
        speaker = (entry.get("speaker") or "").strip()
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        role = "assistant" if speaker == "Speaker 2" else "user"
        out.append({"role": role, "content": text})
    return out


def extract_reply_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in ("reply", "message", "content", "text", "response"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"].strip()
    return ""


def call_customer_chat_api(
    config: dict[str, Any],
    *,
    transcript: list[dict[str, str]],
    agent_name: str,
    language: str,
) -> str:
    base = (config.get("api_base_url") or "").strip().rstrip("/")
    if not base:
        raise ValueError("Customer API base URL is not configured on this agent.")

    path = (config.get("api_message_path") or "/chat").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    url = urljoin(f"{base}/", path.lstrip("/"))

    from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime

    cfg = chat_connection_config_for_runtime(config)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    auth_header = (cfg.get("api_auth_header") or config.get("api_auth_header") or "").strip()
    auth_value = (cfg.get("api_auth_value") or "").strip()
    if auth_header and auth_value:
        headers[auth_header] = auth_value

    timeout = float(config.get("timeout_secs") or DEFAULT_TIMEOUT_SECS)
    body = {
        "messages": _openai_style_messages(transcript),
        "transcript": transcript,
        "agent_name": agent_name,
        "language": language,
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        try:
            data = response.json()
        except Exception:
            text = response.text.strip()
            if not text:
                raise ValueError("Customer API returned an empty response")
            return text
        reply = extract_reply_text(data)
        if not reply:
            raise ValueError("Customer API response did not include a reply message")
        return reply
