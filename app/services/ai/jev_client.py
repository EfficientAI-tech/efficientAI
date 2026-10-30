"""Typed Jev decision client (TypeSafe systemone endpoint)."""

from __future__ import annotations

import time
from typing import Any

import requests


JEV_DECIDE_URL = "https://api.typesafe.ai/v1/systemone"
_RETRYABLE_STATUS = {429, 529}


class JevClientError(RuntimeError):
    """Raised when Jev request fails permanently."""


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("detail")
        if detail:
            return str(detail)
    body = (response.text or "").strip()
    return body or f"HTTP {response.status_code}"


def decide(
    *,
    state: Any,
    questions: dict[str, Any],
    model: str,
    api_key: str,
    timeout_s: float = 45.0,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """Call TypeSafe Jev `/v1/systemone` with bounded retries."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "state": state,
        "model": model,
        "questions": questions,
    }
    backoff_s = 0.75
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                JEV_DECIDE_URL,
                headers=headers,
                json=payload,
                timeout=timeout_s,
            )
        except requests.RequestException as exc:
            last_err = exc
            if attempt < max_attempts:
                time.sleep(backoff_s)
                backoff_s *= 2
                continue
            raise JevClientError(f"Jev request failed: {exc}") from exc

        if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts:
            time.sleep(backoff_s)
            backoff_s *= 2
            continue

        if response.status_code == 401:
            raise JevClientError("Jev authentication failed (401). Check TypeSafe API key.")
        if response.status_code == 422:
            raise JevClientError(
                f"Jev request validation failed (422): {_error_message(response)}"
            )
        if response.status_code >= 400:
            raise JevClientError(
                f"Jev request failed ({response.status_code}): {_error_message(response)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise JevClientError("Jev returned non-JSON response.") from exc
        if not isinstance(data, dict):
            raise JevClientError("Jev returned invalid response shape.")
        return data

    # Defensive fallback.
    if last_err is not None:
        raise JevClientError(f"Jev request failed: {last_err}") from last_err
    raise JevClientError("Jev request failed after retries.")
