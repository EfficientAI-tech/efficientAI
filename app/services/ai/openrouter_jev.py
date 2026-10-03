"""Jev (TypeSafe decision) calls via the System One API.

Direct routing posts to OpenRouter's ``/api/v1/systemone``. When the org routes
LLM traffic through a gateway, the call goes to the gateway's TypeSafe
pass-through instead (Bifrost and LiteLLM Proxy both expose TypeSafe's native
API 1:1 under ``/typesafe``), so the gateway's auth, logging and spend
tracking apply. Request and response bodies are identical on both paths.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

OPENROUTER_SYSTEMONE_URL = "https://openrouter.ai/api/v1/systemone"
GATEWAY_SYSTEMONE_PATH = "/typesafe/v1/systemone"
# Suffixes the gateway config appends to its base URL for chat completions
# (Bifrost LiteLLM shim: /litellm, Bifrost native and some proxies: /v1).
_GATEWAY_API_SUFFIXES = ("/litellm", "/v1")


def is_openrouter_jev_model(provider_value: str, model: str | None) -> bool:
    if (provider_value or "").lower() != "openrouter":
        return False
    lowered = (model or "").lower()
    return "jev" in lowered


def normalize_openrouter_jev_model_id(model: str) -> str:
    slug = (model or "").strip()
    if slug.lower().startswith("openrouter/"):
        slug = slug.split("/", 1)[1]
    if not slug.lower().startswith("typesafe/") and slug.lower().startswith("jev"):
        slug = f"typesafe/{slug}"
    return slug


def normalize_typesafe_model_id(model: str) -> str:
    """TypeSafe's native model id (``jev-1.13.0``): no ``openrouter/`` or ``typesafe/`` prefix."""
    slug = (model or "").strip()
    for prefix in ("openrouter/", "typesafe/"):
        if slug.lower().startswith(prefix):
            slug = slug[len(prefix):]
    return slug


def gateway_systemone_url(api_base: str) -> str:
    """Gateway TypeSafe pass-through URL from the gateway's chat ``api_base``."""
    root = (api_base or "").strip().rstrip("/")
    for suffix in _GATEWAY_API_SUFFIXES:
        if root.endswith(suffix):
            root = root[: -len(suffix)]
            break
    if not root:
        raise RuntimeError("LLM gateway has no base URL; cannot route the Jev System One call.")
    return f"{root}{GATEWAY_SYSTEMONE_PATH}"


def extract_jev_payload(
    messages: List[Dict[str, str]],
    completion_extra: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """Return (state, questions) when the call is a Jev structured evaluation."""
    questions: Optional[Dict[str, Any]] = None
    if completion_extra:
        response_format = completion_extra.get("response_format") or {}
        if response_format.get("type") == "questions":
            raw_questions = response_format.get("questions")
            if isinstance(raw_questions, dict) and raw_questions:
                questions = raw_questions

    state: Any = None
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content") or ""
        if questions is not None:
            state = content
            break
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("questions") and isinstance(parsed["questions"], dict):
            questions = parsed["questions"]
        if "state" in parsed:
            state = parsed["state"]
        if state is not None and questions:
            return state, questions

    if state is not None and questions:
        return state, questions
    return None


def systemone_response_to_text(response_body: Dict[str, Any]) -> str:
    answers = response_body.get("answers")
    if isinstance(answers, dict):
        return json.dumps({"answers": answers})
    return json.dumps(response_body)


def call_systemone(
    *,
    url: str,
    api_key: str,
    model_id: str,
    state: Any,
    questions: Dict[str, Any],
    extra_headers: Optional[Dict[str, str]] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """POST a System One request (OpenRouter or a gateway's TypeSafe pass-through)."""
    payload = {"model": model_id, "state": state, "questions": questions}
    headers = {
        **(extra_headers or {}),
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"System One request to {url} failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"System One request to {url} failed: {exc}") from exc

    if not isinstance(body, dict):
        raise RuntimeError(f"System One at {url} returned a non-object response")
    return body


def call_openrouter_systemone(
    *,
    api_key: str,
    model: str,
    state: Any,
    questions: Dict[str, Any],
    timeout: float = 120.0,
) -> Dict[str, Any]:
    return call_systemone(
        url=OPENROUTER_SYSTEMONE_URL,
        api_key=api_key,
        model_id=normalize_openrouter_jev_model_id(model),
        state=state,
        questions=questions,
        timeout=timeout,
    )
