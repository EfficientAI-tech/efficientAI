"""Map OTLP span attributes to per-turn synthetic trace fields."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_CALL_SHORT_ID_RE = re.compile(r"^\d{6}$")

_LLM_OPS = frozenset({"chat", "llm", "llm_response"})
_LLM_NAMES = frozenset({"llm", "llm_response"})
_S2S_OPS = frozenset({"s2s", "realtime", "llm_response"})
_S2S_NAMES = frozenset({"s2s"})
_REALTIME_PROVIDER_HINTS = ("gemini", "realtime", "nova", "openai")


def _attr_str(attrs: Dict[str, Any], key: str) -> Optional[str]:
    val = attrs.get(key)
    if val is None:
        return None
    return str(val)


def _attr_float(attrs: Dict[str, Any], key: str) -> Optional[float]:
    val = attrs.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _ms_from_ttfb(attrs: Dict[str, Any]) -> Optional[float]:
    ttfb = _attr_float(attrs, "metrics.ttfb")
    if ttfb is None:
        return None
    return round(ttfb * 1000.0, 1)


def _ms_from_span_duration(span: Dict[str, Any]) -> Optional[float]:
    start = span.get("start_time_unix_nano")
    end = span.get("end_time_unix_nano")
    if start is None or end is None:
        return None
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        return None
    if end_i <= start_i:
        return None
    return round((end_i - start_i) / 1_000_000.0, 1)


def _span_index(spans: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for span in spans:
        span_id = span.get("span_id")
        if span_id:
            out[str(span_id)] = span
    return out


def _build_turn_span_display_map(
    spans: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Assign sequential display turn numbers to turn spans ordered by start time."""
    turn_rows: List[tuple[int, str]] = []
    for span in spans:
        if (span.get("name") or "").lower() != "turn":
            continue
        span_id = span.get("span_id")
        if not span_id:
            continue
        start = span.get("start_time_unix_nano")
        try:
            start_i = int(start) if start is not None else 0
        except (TypeError, ValueError):
            start_i = 0
        turn_rows.append((start_i, str(span_id)))

    turn_rows.sort(key=lambda row: row[0])
    return {span_id: idx + 1 for idx, (_, span_id) in enumerate(turn_rows)}


def _span_start_ns(span: Dict[str, Any]) -> Optional[int]:
    start = span.get("start_time_unix_nano")
    if start is None:
        return None
    try:
        return int(start)
    except (TypeError, ValueError):
        return None


def _build_turn_windows(
    spans: List[Dict[str, Any]],
    turn_display: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Chronological turn windows for assigning orphan component spans."""
    windows: List[Dict[str, Any]] = []
    for span in spans:
        if (span.get("name") or "").lower() != "turn":
            continue
        span_id = span.get("span_id")
        if not span_id or str(span_id) not in turn_display:
            continue
        start = _span_start_ns(span) or 0
        end_raw = span.get("end_time_unix_nano")
        try:
            end = int(end_raw) if end_raw is not None else start
        except (TypeError, ValueError):
            end = start
        windows.append(
            {
                "display_num": turn_display[str(span_id)],
                "start": start,
                "end": max(end, start),
                "span_id": str(span_id),
            }
        )
    windows.sort(key=lambda row: row["start"])
    for idx, window in enumerate(windows):
        next_start = windows[idx + 1]["start"] if idx + 1 < len(windows) else None
        window["window_end"] = (
            next_start if next_start is not None else window["end"] + 30_000_000_000
        )
    return windows


def _turn_for_time(windows: List[Dict[str, Any]], start_ns: Optional[int]) -> Optional[int]:
    if start_ns is None or not windows:
        return None
    for window in windows:
        if window["start"] <= start_ns < window["window_end"]:
            return int(window["display_num"])
    best: Optional[int] = None
    for window in windows:
        if window["start"] <= start_ns:
            best = int(window["display_num"])
    return best


def _resolve_turn_number(
    span: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    turn_display: Optional[Dict[str, int]] = None,
    turn_windows: Optional[List[Dict[str, Any]]] = None,
) -> Optional[int]:
    visited: set[str] = set()
    current: Optional[Dict[str, Any]] = span
    while current is not None:
        span_id = current.get("span_id")
        if span_id and turn_display and str(span_id) in turn_display:
            return turn_display[str(span_id)]

        attrs = current.get("attributes") or {}
        display = attrs.get("efficientai.display_turn_number")
        if display is not None:
            try:
                return int(display)
            except (TypeError, ValueError):
                pass

        if span_id:
            if span_id in visited:
                break
            visited.add(str(span_id))

        parent_id = current.get("parent_span_id")
        if not parent_id:
            break
        current = by_id.get(str(parent_id))

    if turn_windows:
        start_ns = _span_start_ns(span)
        if start_ns is not None:
            by_time = _turn_for_time(turn_windows, start_ns)
            if by_time is not None:
                return by_time

    attrs = span.get("attributes") or {}
    turn_num = _attr_float(attrs, "turn.number")
    if turn_num is not None:
        return int(turn_num)
    return None


def annotate_spans_with_display_turn(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach efficientai.display_turn_number for UI grouping."""
    if not spans:
        return []
    turns = derive_turns_from_spans(spans)
    span_map = _span_display_map_from_turns(turns)
    turn_display = _build_turn_span_display_map(spans)
    turn_windows = _build_turn_windows(spans, turn_display)
    by_id = _span_index(spans)
    annotated: List[Dict[str, Any]] = []
    for span in spans:
        row = dict(span)
        span_id = row.get("span_id")
        turn_num = span_map.get(str(span_id)) if span_id else None
        if turn_num is None:
            turn_num = _resolve_turn_number(row, by_id, turn_display, turn_windows)
        if turn_num is not None:
            attrs = dict(row.get("attributes") or {})
            attrs["efficientai.display_turn_number"] = turn_num
            row["attributes"] = attrs
        annotated.append(row)
    return annotated


def _component_field(op: str, name: str) -> Optional[str]:
    if op == "stt" or name == "stt":
        return "stt_ttfb_ms"
    if op in _LLM_OPS or name in _LLM_NAMES:
        return "llm_ttfb_ms"
    if op == "tts" or name == "tts":
        return "tts_ttfb_ms"
    if op == "s2s" or name == "s2s":
        return "s2s_ttfb_ms"
    return None


def _is_s2s_span(op: str, name: str, attrs: Dict[str, Any]) -> bool:
    if op == "s2s" or name in _S2S_NAMES:
        return True
    provider = str(
        attrs.get("gen_ai.provider.name") or attrs.get("gen_ai.system") or ""
    ).lower()
    model = str(attrs.get("gen_ai.request.model") or "").lower()
    if name in _S2S_OPS and any(hint in provider or hint in model for hint in _REALTIME_PROVIDER_HINTS):
        if "realtime" in model or "live" in model or "nova" in model or "sonic" in model:
            return True
        modalities = str(attrs.get("modalities") or "").upper()
        if "AUDIO" in modalities:
            return True
    return False


def _new_turn() -> Dict[str, Any]:
    return {"turn_number": 0, "extra": {"_span_ids": []}}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _text_similar(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    na, nb = _normalize_text(str(a)), _normalize_text(str(b))
    if na == nb:
        return True
    if len(na) >= 20 and (na in nb or nb in na):
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) >= 15 and longer.startswith(shorter[:15])


def _turn_has_content(turn: Dict[str, Any]) -> bool:
    extra = turn.get("extra") or {}
    return bool(
        extra.get("user_text")
        or extra.get("assistant_text")
        or turn.get("stt_ttfb_ms")
        or turn.get("llm_ttfb_ms")
        or turn.get("tts_ttfb_ms")
        or turn.get("s2s_ttfb_ms")
    )


def _short_model_name(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("accounts/") and "/models/" in text:
        return text.split("/models/", 1)[-1].split("/", 1)[0]
    if "/" in text:
        return text.rsplit("/", 1)[-1]
    return text


def _component_meta_from_attrs(attrs: Dict[str, Any], kind: str) -> Dict[str, Optional[str]]:
    model = attrs.get("gen_ai.request.model") or attrs.get("param.model")
    if kind in ("tts", "stt"):
        model = model or attrs.get("settings.model")
    provider = attrs.get("gen_ai.provider.name") or attrs.get("gen_ai.system")
    return {
        "model": _short_model_name(model),
        "provider": str(provider).strip().lower() if provider else None,
    }


def _set_component_meta(turn: Dict[str, Any], kind: str, attrs: Dict[str, Any]) -> None:
    meta = _component_meta_from_attrs(attrs, kind)
    extra = turn.setdefault("extra", {})
    if meta.get("model"):
        extra[f"{kind}_model"] = meta["model"]
    if meta.get("provider"):
        extra[f"{kind}_provider"] = meta["provider"]


def extract_pipeline_models(spans: List[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[str]]]:
    """Session-level STT/LLM/TTS/S2S model + provider from OTLP spans."""
    pipeline: Dict[str, Dict[str, Optional[str]]] = {}

    def _set(kind: str, attrs: Dict[str, Any]) -> None:
        meta = _component_meta_from_attrs(attrs, kind)
        if not meta.get("model") and not meta.get("provider"):
            return
        row = pipeline.setdefault(kind, {})
        if meta.get("model") and not row.get("model"):
            row["model"] = meta["model"]
        if meta.get("provider") and not row.get("provider"):
            row["provider"] = meta["provider"]

    for span in spans:
        attrs = span.get("attributes") or {}
        op = (_attr_str(attrs, "gen_ai.operation.name") or "").lower()
        name = (span.get("name") or "").lower()
        if _is_s2s_span(op, name, attrs):
            _set("s2s", attrs)
        elif op == "stt" or name == "stt":
            _set("stt", attrs)
        elif op in _LLM_OPS or name in _LLM_NAMES:
            _set("llm", attrs)
        elif op == "tts" or name == "tts":
            _set("tts", attrs)

    return pipeline


def _collect_component_events(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for span in spans:
        attrs = span.get("attributes") or {}
        op = (_attr_str(attrs, "gen_ai.operation.name") or "").lower()
        name = (span.get("name") or "").lower()
        start = _span_start_ns(span) or 0
        span_id = span.get("span_id")

        if _is_s2s_span(op, name, attrs):
            transcript = attrs.get("transcript")
            is_input = attrs.get("transcript.is_input")
            output = attrs.get("output") or attrs.get("text_output")
            meta = _component_meta_from_attrs(attrs, "s2s")
            events.append(
                {
                    "type": "s2s",
                    "span_id": span_id,
                    "start": start,
                    "latency_ms": _component_latency_ms(span, attrs, "llm_ttfb_ms"),
                    "user_text": str(transcript)
                    if transcript and is_input
                    else None,
                    "assistant_text": str(output)
                    if output
                    else (str(transcript) if transcript and not is_input else None),
                    "agent_id": attrs.get("efficientai.agent_id"),
                    "model": meta.get("model"),
                    "provider": meta.get("provider"),
                    "attrs": attrs,
                }
            )
            continue

        if op == "stt" or name == "stt":
            meta = _component_meta_from_attrs(attrs, "stt")
            events.append(
                {
                    "type": "stt",
                    "span_id": span_id,
                    "start": start,
                    "latency_ms": _component_latency_ms(span, attrs, "stt_ttfb_ms"),
                    "user_text": str(attrs["transcript"]) if attrs.get("transcript") else None,
                    "agent_id": attrs.get("efficientai.agent_id"),
                    "model": meta.get("model"),
                    "provider": meta.get("provider"),
                    "attrs": attrs,
                }
            )
        elif op in _LLM_OPS or name in _LLM_NAMES:
            output = attrs.get("output") or attrs.get("text_output")
            meta = _component_meta_from_attrs(attrs, "llm")
            events.append(
                {
                    "type": "llm",
                    "span_id": span_id,
                    "start": start,
                    "latency_ms": _component_latency_ms(span, attrs, "llm_ttfb_ms"),
                    "assistant_text": str(output) if output else None,
                    "agent_id": attrs.get("efficientai.agent_id"),
                    "model": meta.get("model"),
                    "provider": meta.get("provider"),
                    "attrs": attrs,
                }
            )
        elif op == "tts" or name == "tts":
            spoken = attrs.get("text") or attrs.get("output")
            meta = _component_meta_from_attrs(attrs, "tts")
            events.append(
                {
                    "type": "tts",
                    "span_id": span_id,
                    "start": start,
                    "latency_ms": _component_latency_ms(span, attrs, "tts_ttfb_ms"),
                    "assistant_text": str(spoken) if spoken else None,
                    "agent_id": attrs.get("efficientai.agent_id"),
                    "model": meta.get("model"),
                    "provider": meta.get("provider"),
                    "attrs": attrs,
                }
            )

    events.sort(key=lambda row: (row["start"], row["type"]))
    return events


def _apply_event_meta(turn: Dict[str, Any], event: Dict[str, Any]) -> None:
    kind = str(event.get("type") or "")
    if not kind:
        return
    attrs = event.get("attrs")
    if isinstance(attrs, dict):
        _set_component_meta(turn, kind, attrs)
        return
    extra = turn.setdefault("extra", {})
    if event.get("model"):
        extra[f"{kind}_model"] = str(event["model"])
    if event.get("provider"):
        extra[f"{kind}_provider"] = str(event["provider"])


def _track_span(turn: Dict[str, Any], span_id: Any) -> None:
    if not span_id:
        return
    extra = turn.setdefault("extra", {})
    ids = extra.setdefault("_span_ids", [])
    sid = str(span_id)
    if sid not in ids:
        ids.append(sid)


def _find_turn_for_tts(
    turns: List[Dict[str, Any]],
    current: Optional[Dict[str, Any]],
    text: Optional[str],
) -> Dict[str, Any]:
    if text:
        for turn in reversed(turns):
            if _text_similar(text, (turn.get("extra") or {}).get("assistant_text")):
                return turn
        if current and _text_similar(text, (current.get("extra") or {}).get("assistant_text")):
            return current
    for turn in reversed(turns):
        if turn.get("llm_ttfb_ms") and not turn.get("tts_ttfb_ms"):
            return turn
    if current and current.get("llm_ttfb_ms") and not current.get("tts_ttfb_ms"):
        return current
    return current if current is not None else _new_turn()


def _apply_turn_span_metadata(
    turns: List[Dict[str, Any]],
    turn_spans: List[Dict[str, Any]],
) -> None:
    meta_spans = sorted(turn_spans, key=lambda s: _span_start_ns(s) or 0)
    response_turns = [
        t
        for t in turns
        if (t.get("extra") or {}).get("assistant_text") or t.get("s2s_ttfb_ms")
    ]
    for idx, span in enumerate(meta_spans):
        if idx >= len(response_turns):
            break
        turn = response_turns[idx]
        attrs = span.get("attributes") or {}
        user_bot_s = _attr_float(attrs, "turn.user_bot_latency_seconds")
        if user_bot_s is not None:
            _set_max_ms(turn, "sut_response_latency_ms", round(user_bot_s * 1000.0, 1))
        if attrs.get("turn.was_interrupted"):
            turn.setdefault("extra", {})["was_interrupted"] = True
        duration_s = _attr_float(attrs, "turn.duration_seconds")
        if duration_s is not None:
            turn.setdefault("extra", {})["turn_duration_seconds"] = duration_s


def _detect_turn_pipeline_mode(turn: Dict[str, Any]) -> None:
    extra = turn.setdefault("extra", {})
    if extra.get("pipeline_mode") == "s2s" or turn.get("s2s_ttfb_ms"):
        extra["pipeline_mode"] = "s2s"
        return
    if any(turn.get(k) for k in ("stt_ttfb_ms", "llm_ttfb_ms", "tts_ttfb_ms")):
        extra["pipeline_mode"] = "stt_llm_tts"


def _merge_turn_fields(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for field in ("stt_ttfb_ms", "llm_ttfb_ms", "tts_ttfb_ms", "s2s_ttfb_ms", "sut_response_latency_ms"):
        _set_max_ms(target, field, source.get(field))
    src_extra = source.get("extra") or {}
    tgt_extra = target.setdefault("extra", {})
    for key in (
        "user_text",
        "assistant_text",
        "agent_id",
        "s2s_model",
        "pipeline_mode",
        "stt_model",
        "llm_model",
        "tts_model",
        "stt_provider",
        "llm_provider",
        "tts_provider",
        "s2s_provider",
    ):
        if src_extra.get(key) and not tgt_extra.get(key):
            tgt_extra[key] = src_extra[key]
    for span_id in src_extra.get("_span_ids") or []:
        _track_span(target, span_id)
    if src_extra.get("was_interrupted"):
        tgt_extra["was_interrupted"] = True


def _pair_user_response_turns(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order turns as opener → user+bot exchanges; merge split async components."""
    if len(turns) <= 1:
        return turns

    def _has_user(t: Dict[str, Any]) -> bool:
        return bool((t.get("extra") or {}).get("user_text"))

    def _has_assistant(t: Dict[str, Any]) -> bool:
        return bool((t.get("extra") or {}).get("assistant_text"))

    openers = [t for t in turns if _has_assistant(t) and not _has_user(t)]
    user_turns = [t for t in turns if _has_user(t) and not _has_assistant(t)]
    combined = [t for t in turns if _has_user(t) and _has_assistant(t)]
    bot_only = [t for t in turns if _has_assistant(t) and not _has_user(t)]

    if not user_turns:
        return turns

    opener = openers[0] if openers else None
    response_pool = [t for t in bot_only if t is not opener]

    ordered: List[Dict[str, Any]] = []
    if opener:
        ordered.append(opener)

    for user_turn in user_turns:
        merged = dict(user_turn)
        merged_extra = dict(merged.get("extra") or {})
        merged["extra"] = merged_extra
        if response_pool:
            bot = response_pool.pop(0)
            _merge_turn_fields(merged, bot)
        ordered.append(merged)

    for leftover in response_pool:
        ordered.append(leftover)
    ordered.extend(combined)
    return [t for t in ordered if _turn_has_content(t)]


def _rebuild_conversation_turns(spans: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    events = _collect_component_events(spans)
    has_timing = any((e.get("start") or 0) > 0 for e in events)
    if not events or not has_timing:
        return None

    turn_meta = [s for s in spans if (s.get("name") or "").lower() == "turn"]
    turns: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if current and _turn_has_content(current):
            turns.append(current)
        current = None

    def ensure_current() -> Dict[str, Any]:
        nonlocal current
        if current is None:
            current = _new_turn()
        return current

    for event in events:
        span_id = event.get("span_id")
        event_type = event["type"]

        if event_type == "stt":
            transcript = event.get("user_text")
            if transcript:
                t = ensure_current()
                if (t.get("extra") or {}).get("assistant_text"):
                    flush()
                    t = ensure_current()
                if (t.get("extra") or {}).get("user_text") and not _text_similar(
                    transcript, t["extra"]["user_text"]
                ):
                    flush()
                    t = ensure_current()
                _track_span(t, span_id)
                _set_turn_text(t, "user", transcript)
                _set_max_ms(t, "stt_ttfb_ms", event.get("latency_ms"))
                _apply_event_meta(t, event)
            continue

        if event_type == "llm":
            t = ensure_current()
            output = event.get("assistant_text")
            if output and (t.get("extra") or {}).get("assistant_text") and not _text_similar(
                output, t["extra"]["assistant_text"]
            ):
                flush()
                t = ensure_current()
            _track_span(t, span_id)
            if output:
                _set_turn_text(t, "assistant", output)
            _set_max_ms(t, "llm_ttfb_ms", event.get("latency_ms"))
            _apply_event_meta(t, event)
            if event.get("agent_id"):
                t.setdefault("extra", {})["agent_id"] = str(event["agent_id"])
            continue

        if event_type == "tts":
            target = _find_turn_for_tts(turns, current, event.get("assistant_text"))
            _track_span(target, span_id)
            if event.get("assistant_text"):
                _set_turn_text(target, "assistant", str(event["assistant_text"]))
            _set_max_ms(target, "tts_ttfb_ms", event.get("latency_ms"))
            _apply_event_meta(target, event)
            if target is current:
                current = target
            elif target not in turns:
                current = target
            continue

        if event_type == "s2s":
            t = ensure_current()
            if event.get("user_text"):
                if (t.get("extra") or {}).get("assistant_text"):
                    flush()
                    t = ensure_current()
                _set_turn_text(t, "user", str(event["user_text"]))
            if event.get("assistant_text"):
                _set_turn_text(t, "assistant", str(event["assistant_text"]))
            _track_span(t, span_id)
            _set_max_ms(t, "s2s_ttfb_ms", event.get("latency_ms"))
            _apply_event_meta(t, event)
            t.setdefault("extra", {})["pipeline_mode"] = "s2s"
            if event.get("agent_id"):
                t["extra"]["agent_id"] = str(event["agent_id"])

    flush()
    turns = [t for t in turns if _turn_has_content(t)]
    if not turns:
        return None

    turns = _pair_user_response_turns(turns)

    _apply_turn_span_metadata(turns, turn_meta)
    for idx, turn in enumerate(turns, start=1):
        turn["turn_number"] = idx
        _finalize_turn_metrics(turn)
        _detect_turn_pipeline_mode(turn)
    return turns


def _set_max_ms(turn: Dict[str, Any], field: str, value: Optional[float]) -> None:
    if value is None or float(value) <= 0:
        return
    existing = turn.get(field)
    if existing is None or float(value) > float(existing):
        turn[field] = value


def _component_latency_ms(
    span: Dict[str, Any],
    attrs: Dict[str, Any],
    field: str,
) -> Optional[float]:
    ttfb_ms = _ms_from_ttfb(attrs)
    if ttfb_ms is not None and ttfb_ms > 0:
        return ttfb_ms
    if field == "stt_ttfb_ms":
        return None
    duration_ms = _ms_from_span_duration(span)
    if duration_ms is not None and duration_ms > 0:
        return duration_ms
    return None


def _looks_like_chat_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("[{") or stripped.startswith('{"role"')


def _set_turn_text(turn: Dict[str, Any], role: str, text: str) -> None:
    extra = turn.setdefault("extra", {})
    key = "user_text" if role == "user" else "assistant_text"
    cleaned = text.strip()
    if not cleaned or _looks_like_chat_json(cleaned):
        return
    existing = extra.get(key)
    if existing is None or len(cleaned) > len(str(existing)):
        extra[key] = cleaned


def _build_transcript_display(turn: Dict[str, Any]) -> None:
    extra = turn.get("extra") or {}
    user = extra.get("user_text")
    assistant = extra.get("assistant_text")
    parts: List[str] = []
    if user:
        parts.append(f"User: {user}")
    if assistant:
        parts.append(f"Assistant: {assistant}")
    if parts:
        turn["transcript"] = "\n".join(parts)


def _finalize_turn_metrics(turn: Dict[str, Any]) -> None:
    """Derive composite fields after all spans for a turn are collected."""
    s2s = turn.get("s2s_ttfb_ms")
    llm = turn.get("llm_ttfb_ms")
    if turn.get("sut_response_latency_ms") is None:
        if s2s is not None:
            turn["sut_response_latency_ms"] = s2s
        elif llm is not None:
            turn["sut_response_latency_ms"] = llm

    if (turn.get("extra") or {}).get("pipeline_mode") == "s2s":
        _build_transcript_display(turn)
        return

    sut = turn.get("sut_response_latency_ms")
    llm = turn.get("llm_ttfb_ms")
    if turn.get("tts_ttfb_ms") is None and sut is not None and llm is not None:
        derived_tts = round(float(sut) - float(llm), 1)
        if derived_tts > 0:
            turn["tts_ttfb_ms"] = derived_tts

    _build_transcript_display(turn)


def derive_turns_from_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project OTLP spans onto per-turn records for Tier 1+2 combined view."""
    rebuilt = _rebuild_conversation_turns(spans)
    if rebuilt is not None:
        return rebuilt
    return _derive_turns_by_pipecat_turn(spans)


def _span_display_map_from_turns(turns: List[Dict[str, Any]]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for turn in turns:
        turn_num = int(turn.get("turn_number") or 0)
        for span_id in (turn.get("extra") or {}).get("_span_ids") or []:
            mapping[str(span_id)] = turn_num
    return mapping


def _derive_turns_by_pipecat_turn(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = _span_index(spans)
    turn_display = _build_turn_span_display_map(spans)
    turn_windows = _build_turn_windows(spans, turn_display)
    turn_spans: Dict[int, Dict[str, Any]] = {}

    for span in spans:
        turn_key = _resolve_turn_number(span, by_id, turn_display, turn_windows)
        if turn_key is None:
            continue

        attrs = span.get("attributes") or {}
        turn = turn_spans.setdefault(
            turn_key,
            {"turn_number": turn_key, "extra": {}},
        )

        op = (_attr_str(attrs, "gen_ai.operation.name") or "").lower()
        name = (span.get("name") or "").lower()

        agent_id = attrs.get("efficientai.agent_id")
        if agent_id and not turn["extra"].get("agent_id"):
            turn["extra"]["agent_id"] = str(agent_id)

        if name == "turn":
            user_bot_s = _attr_float(attrs, "turn.user_bot_latency_seconds")
            if user_bot_s is not None:
                _set_max_ms(
                    turn,
                    "sut_response_latency_ms",
                    round(user_bot_s * 1000.0, 1),
                )
            duration_s = _attr_float(attrs, "turn.duration_seconds")
            if duration_s is not None:
                turn["extra"]["turn_duration_seconds"] = duration_s
            if attrs.get("turn.was_interrupted"):
                turn["extra"]["was_interrupted"] = True
            turn_type = _attr_str(attrs, "turn.type")
            if turn_type:
                turn["extra"]["turn_type"] = turn_type
            continue

        field = _component_field(op, name)
        if field:
            _set_max_ms(turn, field, _component_latency_ms(span, attrs, field))
            kind = "s2s" if field == "s2s_ttfb_ms" else field.removesuffix("_ttfb_ms")
            _set_component_meta(turn, kind, attrs)
            if field == "stt_ttfb_ms" and attrs.get("transcript"):
                _set_turn_text(turn, "user", str(attrs["transcript"]))
            if field == "llm_ttfb_ms":
                output = attrs.get("output")
                if output:
                    _set_turn_text(turn, "assistant", str(output))
            if field == "tts_ttfb_ms":
                spoken = attrs.get("text") or attrs.get("output")
                if spoken and not turn["extra"].get("assistant_text"):
                    _set_turn_text(turn, "assistant", str(spoken))

    for turn in turn_spans.values():
        _finalize_turn_metrics(turn)
        _detect_turn_pipeline_mode(turn)

    return [turn_spans[k] for k in sorted(turn_spans)]


def merge_tier1_and_otel_turns(
    tier1_turns: List[Dict[str, Any]],
    otel_turns: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge black-box phone timings with OTLP-derived component fields."""
    otel_by_num = {int(t["turn_number"]): t for t in otel_turns if t.get("turn_number")}
    merged: List[Dict[str, Any]] = []
    seen: set[int] = set()

    for turn in tier1_turns:
        num = int(turn.get("turn_number") or 0)
        seen.add(num)
        combined = dict(turn)
        if num in otel_by_num:
            for key in (
                "stt_ttfb_ms",
                "llm_ttfb_ms",
                "tts_ttfb_ms",
                "s2s_ttfb_ms",
                "sut_response_latency_ms",
                "transcript",
                "extra",
            ):
                if key not in otel_by_num[num] or otel_by_num[num][key] is None:
                    continue
                if key == "sut_response_latency_ms" and combined.get(key) is not None:
                    continue
                combined[key] = otel_by_num[num][key]
        merged.append(combined)

    for num, turn in otel_by_num.items():
        if num not in seen:
            merged.append(dict(turn))

    merged.sort(key=lambda t: int(t.get("turn_number") or 0))
    return merged


def compute_component_aggregates(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    def _percentile(values: List[float], pct: float) -> Optional[float]:
        if not values:
            return None
        sorted_vals = sorted(values)
        idx = min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1))))
        return round(sorted_vals[idx], 1)

    agg: Dict[str, Any] = {}
    for field in (
        "stt_ttfb_ms",
        "llm_ttfb_ms",
        "tts_ttfb_ms",
        "s2s_ttfb_ms",
        "sut_response_latency_ms",
    ):
        values = [float(t[field]) for t in turns if t.get(field) is not None]
        if values:
            agg[field] = {
                "p50": _percentile(values, 50),
                "p90": _percentile(values, 90),
                "p95": _percentile(values, 95),
                "count": len(values),
            }
    return agg


def compute_trace_latency_summary(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute header percentiles and component aggregates from turn rows."""
    aggregates = compute_component_aggregates(turns)
    sut_values = [
        float(t["sut_response_latency_ms"])
        for t in turns
        if t.get("sut_response_latency_ms") is not None
    ]
    if not sut_values:
        sut_values = [
            float(t["s2s_ttfb_ms"]) for t in turns if t.get("s2s_ttfb_ms") is not None
        ]
    if not sut_values:
        sut_values = [
            float(t["llm_ttfb_ms"]) for t in turns if t.get("llm_ttfb_ms") is not None
        ]

    def _pct(values: List[float], pct: float) -> Optional[float]:
        if not values:
            return None
        sorted_vals = sorted(values)
        idx = min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1))))
        return round(sorted_vals[idx], 1)

    return {
        "turn_count": len(turns),
        "response_latency_p50_ms": _pct(sut_values, 50),
        "response_latency_p90_ms": _pct(sut_values, 90),
        "response_latency_p95_ms": _pct(sut_values, 95),
        "component_aggregates": aggregates or None,
    }


def _span_call_short_id(span: Dict[str, Any]) -> Optional[str]:
    raw = (span.get("attributes") or {}).get("efficientai.call_short_id")
    if not raw:
        return None
    cleaned = str(raw).strip()
    if _CALL_SHORT_ID_RE.match(cleaned):
        return cleaned
    return None


def group_spans_by_call_short_id(
    spans: List[Dict[str, Any]],
    *,
    header_call_short_id: Optional[str] = None,
) -> Dict[Optional[str], List[Dict[str, Any]]]:
    """Partition OTLP spans by per-span call_short_id (span attrs beat HTTP header)."""
    groups: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for span in spans:
        key = _span_call_short_id(span) or header_call_short_id
        groups.setdefault(key, []).append(span)
    return groups


def spans_indicate_session_end(spans: List[Dict[str, Any]]) -> bool:
    """True when OTLP spans signal the voice session finished."""
    for span in spans:
        name = (span.get("name") or "").lower()
        attrs = span.get("attributes") or {}
        if name == "conversation" and span.get("end_time_unix_nano"):
            return True
        if attrs.get("turn.ended_by_conversation_end"):
            return True
        if attrs.get("efficientai.session_end"):
            return True
    return False


def filter_spans_for_trace(
    spans: List[Dict[str, Any]],
    *,
    call_short_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Keep only spans belonging to one call; collapse mixed OTLP trace_ids."""
    if not spans:
        return spans

    if call_short_id:
        matched = [s for s in spans if _span_call_short_id(s) == call_short_id]
        if matched:
            spans = matched

    turn_trace_ids: Dict[str, int] = {}
    for span in spans:
        if (span.get("name") or "").lower() != "turn":
            continue
        trace_id = span.get("trace_id")
        if not trace_id:
            continue
        try:
            start = int(span.get("start_time_unix_nano") or 0)
        except (TypeError, ValueError):
            start = 0
        turn_trace_ids[str(trace_id)] = max(turn_trace_ids.get(str(trace_id), 0), start)

    if len(turn_trace_ids) <= 1:
        return spans

    if call_short_id and spans and all(
        _span_call_short_id(s) == call_short_id for s in spans
    ):
        return spans

    primary_trace_id = min(turn_trace_ids, key=turn_trace_ids.get)
    return [s for s in spans if str(s.get("trace_id") or "") == primary_trace_id]


def extract_correlation_ids(spans: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    for span in spans:
        attrs = span.get("attributes") or {}
        result_id = (
            attrs.get("efficientai.evaluator_result_id")
            or attrs.get("efficientai.run_id")
        )
        call_short_raw = attrs.get("efficientai.call_short_id")
        call_short = (
            str(call_short_raw).strip()
            if call_short_raw and _CALL_SHORT_ID_RE.match(str(call_short_raw).strip())
            else None
        )
        agent_id = attrs.get("efficientai.agent_id")
        transport_raw = attrs.get("efficientai.transport")
        transport = (
            str(transport_raw).strip().lower()
            if transport_raw and str(transport_raw).strip().lower() in {"webrtc", "websocket", "phone", "custom"}
            else None
        )
        if result_id or call_short or agent_id or transport:
            return {
                "evaluator_result_id": str(result_id) if result_id else None,
                "call_short_id": call_short,
                "agent_id": str(agent_id) if agent_id else None,
                "transport": transport,
            }
    return {}
