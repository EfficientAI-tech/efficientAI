"""Persistent WebSocket client for customer-hosted production chat agents."""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urlparse

import websockets.sync.client
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

from app.services.agents.customer_api_chat import extract_reply_text
from app.services.agents.chat_outbound_payload import customer_api_request_body
from app.services.agents.provider_platform_chat import ProviderChatState

DEFAULT_TIMEOUT_SECS = 60.0
_WS_SESSION_KEY = "customer_websocket_session"


class CustomerWebSocketChatSession:
    def __init__(
        self,
        url: str,
        *,
        extra_headers: Optional[dict[str, str]] = None,
        open_timeout: float = 30.0,
    ) -> None:
        self._url = url.strip()
        self._extra_headers = extra_headers or {}
        self._open_timeout = open_timeout
        self._ws: Any = None

    def _connect(self) -> None:
        if self._ws is not None:
            return
        self._ws = websockets.sync.client.connect(
            self._url,
            additional_headers=self._extra_headers,
            open_timeout=self._open_timeout,
        )

    def close(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            pass

    def send_turn(
        self,
        *,
        config: dict[str, Any],
        transcript: list[dict[str, str]],
        agent_name: str,
        language: str,
        timeout: float = DEFAULT_TIMEOUT_SECS,
    ) -> str:
        from app.services.agents.customer_api_chat import _openai_style_messages

        self._connect()
        assert self._ws is not None
        body = customer_api_request_body(
            config,
            openai_messages=_openai_style_messages(transcript),
            transcript=transcript,
            agent_name=agent_name,
            language=language,
        )
        self._ws.send(json.dumps(body))
        raw = self._ws.recv(timeout=timeout)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return extract_reply_text(raw)
        return extract_reply_text(data)


def _session_from_state(state: ProviderChatState) -> Optional[CustomerWebSocketChatSession]:
    session = state.extra.get(_WS_SESSION_KEY)
    return session if isinstance(session, CustomerWebSocketChatSession) else None


def _build_headers(config: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    auth_header = (config.get("websocket_auth_header") or "").strip()
    auth_value = (config.get("websocket_auth_value") or "").strip()
    if auth_header and auth_value:
        headers[auth_header] = auth_value
    return headers


def call_customer_websocket_chat(
    config: dict[str, Any],
    *,
    transcript: list[dict[str, str]],
    agent_name: str,
    language: str,
    state: ProviderChatState,
) -> str:
    url = (config.get("websocket_url") or "").strip()
    if not url:
        raise ValueError("Customer WebSocket URL is not configured on this agent.")
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss"):
        raise ValueError("websocket_url must use ws:// or wss://")

    session = _session_from_state(state)
    if session is None:
        session = CustomerWebSocketChatSession(url, extra_headers=_build_headers(config))
        state.extra[_WS_SESSION_KEY] = session

    timeout = float(config.get("timeout_secs") or DEFAULT_TIMEOUT_SECS)
    return session.send_turn(
        config=config,
        transcript=transcript,
        agent_name=agent_name,
        language=language,
        timeout=timeout,
    )


def close_customer_websocket_session(state: ProviderChatState) -> None:
    session = _session_from_state(state)
    if session is not None:
        session.close()
    state.extra.pop(_WS_SESSION_KEY, None)
