"""OpenRouter Jev (TypeSafe decision) calls via /api/v1/systemone."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

OPENROUTER_SYSTEMONE_URL = "https://openrouter.ai/api/v1/systemone"


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


def call_openrouter_systemone(
    *,
    api_key: str,
    model: str,
    state: Any,
    questions: Dict[str, Any],
    timeout: float = 120.0,
) -> Dict[str, Any]:
    payload = {
        "model": normalize_openrouter_jev_model_id(model),
        "state": state,
        "questions": questions,
    }
    request = urllib.request.Request(
        OPENROUTER_SYSTEMONE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenRouter System One request failed ({exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter System One request failed: {exc}") from exc

    if not isinstance(body, dict):
        raise RuntimeError("OpenRouter System One returned a non-object response")
    return body
