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
            transcript = str(attrs["transcript"]) if attrs.get("transcript") else None
            if transcript and _is_low_signal_transcript(transcript):
                transcript = None
            events.append(
                {
                    "type": "stt",
                    "span_id": span_id,
                    "start": start,
                    "latency_ms": _component_latency_ms(span, attrs, "stt_ttfb_ms"),
                    "user_text": transcript,
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


def _turn_time_bounds(
    turn: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
) -> tuple[Optional[int], Optional[int]]:
    starts: List[int] = []
    ends: List[int] = []
    for span_id in (turn.get("extra") or {}).get("_span_ids") or []:
        span = by_id.get(str(span_id))
        if not span:
            continue
        start = _span_start_ns(span)
        if start is not None:
            starts.append(start)
        end_raw = span.get("end_time_unix_nano")
        if end_raw is not None:
            try:
                ends.append(int(end_raw))
            except (TypeError, ValueError):
                pass
    if not starts:
        return None, None
    return min(starts), max(ends) if ends else max(starts)


def _interval_overlap_ns(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def _turn_earliest_start_ns(
    turn: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
) -> int:
    bounds = _turn_time_bounds(turn, by_id)
    return bounds[0] if bounds[0] is not None else 0


def _apply_turn_span_metadata(
    turns: List[Dict[str, Any]],
    turn_spans: List[Dict[str, Any]],
    all_spans: Optional[List[Dict[str, Any]]] = None,
) -> None:
    by_id = _span_index(all_spans) if all_spans else {}
    for span in sorted(turn_spans, key=lambda s: _span_start_ns(s) or 0):
        attrs = span.get("attributes") or {}
        user_bot_s = _attr_float(attrs, "turn.user_bot_latency_seconds")
        span_id = str(span.get("span_id") or "")
        span_start = _span_start_ns(span) or 0
        end_raw = span.get("end_time_unix_nano")
        try:
            span_end = int(end_raw) if end_raw is not None else span_start
        except (TypeError, ValueError):
            span_end = span_start

        matched: Optional[Dict[str, Any]] = None
        for turn in turns:
            if span_id and span_id in ((turn.get("extra") or {}).get("_span_ids") or []):
                matched = turn
                break

        if matched is None and by_id:
            best_overlap = -1
            for turn in turns:
                t_start, t_end = _turn_time_bounds(turn, by_id)
                if t_start is None:
                    continue
                overlap = _interval_overlap_ns(
                    span_start,
                    max(span_end, span_start),
                    t_start,
                    max(t_end or t_start, t_start),
                )
                if overlap > best_overlap:
                    best_overlap = overlap
                    matched = turn

        if matched is None and turns:
            matched = min(
                turns,
                key=lambda t: abs(_turn_earliest_start_ns(t, by_id) - span_start),
            )

        if matched is None:
            continue

        if user_bot_s is not None:
            _set_max_ms(matched, "sut_response_latency_ms", round(user_bot_s * 1000.0, 1))
            matched.setdefault("extra", {})["sut_measured_e2e"] = True
        if attrs.get("turn.was_interrupted"):
            matched.setdefault("extra", {})["was_interrupted"] = True
        duration_s = _attr_float(attrs, "turn.duration_seconds")
        if duration_s is not None:
            matched.setdefault("extra", {})["turn_duration_seconds"] = duration_s


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


def _is_span_subset_turn(inner: Dict[str, Any], outer: Dict[str, Any]) -> bool:
    inner_ids = set((inner.get("extra") or {}).get("_span_ids") or [])
    outer_ids = set((outer.get("extra") or {}).get("_span_ids") or [])
    if not inner_ids or not outer_ids:
        return False
    return inner_ids <= outer_ids


def _same_sut(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    sut_a = a.get("sut_response_latency_ms")
    sut_b = b.get("sut_response_latency_ms")
    if sut_a is None or sut_b is None:
        return False
    return abs(float(sut_a) - float(sut_b)) <= 1.0


def _turns_represent_same_exchange(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if _is_span_subset_turn(a, b) or _is_span_subset_turn(b, a):
        return True
    extra_a = a.get("extra") or {}
    extra_b = b.get("extra") or {}
    user_a = extra_a.get("user_text")
    user_b = extra_b.get("user_text")
    asst_a = extra_a.get("assistant_text")
    asst_b = extra_b.get("assistant_text")
    if user_a and user_b and _text_similar(str(user_a), str(user_b)):
        return True
    if asst_a and asst_b and _text_similar(str(asst_a), str(asst_b)):
        return True
    return False


def _should_consolidate_adjacent_turns(prev: Dict[str, Any], curr: Dict[str, Any]) -> bool:
    if _turns_represent_same_exchange(prev, curr):
        return True
    if _same_sut(prev, curr):
        extra_p = prev.get("extra") or {}
        extra_c = curr.get("extra") or {}
        user_p = extra_p.get("user_text")
        user_c = extra_c.get("user_text")
        if user_p and user_c and not _text_similar(str(user_p), str(user_c)):
            return False
        return True
    extra_p = prev.get("extra") or {}
    extra_c = curr.get("extra") or {}
    has_user_p = bool(extra_p.get("user_text"))
    has_asst_p = bool(extra_p.get("assistant_text"))
    has_user_c = bool(extra_c.get("user_text"))
    has_asst_c = bool(extra_c.get("assistant_text"))
    if has_user_p and not has_asst_p and has_asst_c and not has_user_c:
        return True
    if has_user_p and has_asst_p and has_asst_c and not has_user_c:
        return True
    return False


def _consolidate_turn_rows(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge split user/bot fragments and drop subset-duplicate rows."""
    if len(turns) <= 1:
        return turns

    merged: List[Dict[str, Any]] = []
    for turn in turns:
        if merged and _should_consolidate_adjacent_turns(merged[-1], turn):
            _merge_turn_fields(merged[-1], turn)
            continue
        absorbed = False
        for existing in merged:
            if _turns_represent_same_exchange(turn, existing):
                _merge_turn_fields(existing, turn)
                absorbed = True
                break
        if not absorbed:
            merged.append(turn)

    deduped: List[Dict[str, Any]] = []
    for turn in merged:
        if any(
            turn is not other
            and _is_span_subset_turn(turn, other)
            for other in merged
        ):
            continue
        deduped.append(turn)
    return deduped


def _match_bot_response_turn(
    user_turn: Dict[str, Any],
    response_pool: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
) -> Optional[int]:
    if not response_pool:
        return None
    user_start = _turn_earliest_start_ns(user_turn, by_id)
    after_user = [
        (idx, bot)
        for idx, bot in enumerate(response_pool)
        if _turn_earliest_start_ns(bot, by_id) >= user_start
    ]
    if after_user:
        return min(after_user, key=lambda row: _turn_earliest_start_ns(row[1], by_id))[0]
    return max(
        range(len(response_pool)),
        key=lambda idx: _turn_earliest_start_ns(response_pool[idx], by_id),
    )


def _pair_user_response_turns(
    turns: List[Dict[str, Any]],
    spans_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Order turns as opener → user+bot exchanges; merge split async components."""
    if len(turns) <= 1:
        return turns

    by_id = spans_by_id or {}

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
    response_pool.sort(key=lambda t: _turn_earliest_start_ns(t, by_id))

    ordered: List[Dict[str, Any]] = []
    if opener:
        opener.setdefault("extra", {})["is_opener"] = True
        ordered.append(opener)

    for user_turn in user_turns:
        merged = dict(user_turn)
        merged_extra = dict(merged.get("extra") or {})
        merged["extra"] = merged_extra
        bot_idx = _match_bot_response_turn(merged, response_pool, by_id)
        if bot_idx is not None:
            bot = response_pool.pop(bot_idx)
            _merge_turn_fields(merged, bot)
        ordered.append(merged)

    for leftover in response_pool:
        ordered.append(leftover)

    for candidate in combined:
        if any(_turns_represent_same_exchange(candidate, existing) for existing in ordered):
            for existing in ordered:
                if _turns_represent_same_exchange(candidate, existing):
                    _merge_turn_fields(existing, candidate)
                    break
            continue
        ordered.append(candidate)

    return _consolidate_turn_rows([t for t in ordered if _turn_has_content(t)])


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

    spans_by_id = _span_index(spans)
    turns = _pair_user_response_turns(turns, spans_by_id)

    _apply_turn_span_metadata(turns, turn_meta, spans)
    for turn in turns:
        turn_extra = turn.setdefault("extra", {})
        if not turn_extra.get("sut_measured_e2e"):
            derived = _derive_sut_from_span_wall_clock(turn, spans_by_id)
            if derived is not None:
                _set_max_ms(turn, "sut_response_latency_ms", derived)
                turn_extra["sut_derived_from_spans"] = True
    for idx, turn in enumerate(turns, start=1):
        turn["turn_number"] = idx
        _finalize_turn_metrics(turn)
        _detect_turn_pipeline_mode(turn)
    turns = _consolidate_turn_rows(turns)
    for idx, turn in enumerate(turns, start=1):
        turn["turn_number"] = idx
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


_LOW_SIGNAL_TRANSCRIPTS = frozenset(
    {"ah", "uh", "um", "hmm", "oh", "eh", "ha", "hm", "er", "mm"}
)


def _is_low_signal_transcript(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s'+]", "", text.strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return True
    if cleaned in _LOW_SIGNAL_TRANSCRIPTS:
        return True
    if len(cleaned) < 3 and " " not in cleaned:
        return True
    return False


def _set_turn_text(turn: Dict[str, Any], role: str, text: str) -> None:
    extra = turn.setdefault("extra", {})
    key = "user_text" if role == "user" else "assistant_text"
    cleaned = text.strip()
    if not cleaned or _looks_like_chat_json(cleaned):
        return
    if role == "user" and _is_low_signal_transcript(cleaned):
        return
    existing = extra.get(key)
    if existing is None or len(cleaned) > len(str(existing)):
        extra[key] = cleaned


def latency_percentile(values: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile (TDD §9.3), rounded to 0.1 ms."""
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = min(
        len(sorted_vals) - 1,
        int(round((pct / 100.0) * (len(sorted_vals) - 1))),
    )
    return round(sorted_vals[idx], 1)


def _derive_sut_from_span_wall_clock(
    turn: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    """Wall-clock user STT start → last response component end for this turn."""
    span_ids = (turn.get("extra") or {}).get("_span_ids") or []
    if not span_ids:
        return None

    user_starts: List[int] = []
    response_ends: List[int] = []

    for span_id in span_ids:
        span = by_id.get(str(span_id))
        if not span:
            continue
        name = (span.get("name") or "").lower()
        attrs = span.get("attributes") or {}
        op = (_attr_str(attrs, "gen_ai.operation.name") or "").lower()
        start = _span_start_ns(span)
        end_raw = span.get("end_time_unix_nano")
        try:
            end = int(end_raw) if end_raw is not None else start
        except (TypeError, ValueError):
            end = start

        if op == "stt" or name == "stt":
            if start is not None:
                user_starts.append(start)
            continue

        is_response = (
            op in _LLM_OPS
            or name in _LLM_NAMES
            or op == "tts"
            or name == "tts"
        )
        if is_response and end is not None:
            response_ends.append(max(end, start or end))

    if not user_starts or not response_ends:
        return None
    delta_ns = max(response_ends) - min(user_starts)
    if delta_ns <= 0:
        return None
    return round(delta_ns / 1_000_000.0, 1)


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
    extra = turn.setdefault("extra", {})
    s2s = turn.get("s2s_ttfb_ms")
    llm = turn.get("llm_ttfb_ms")
    stt = turn.get("stt_ttfb_ms")
    tts = turn.get("tts_ttfb_ms")

    if turn.get("sut_response_latency_ms") is None:
        if s2s is not None:
            turn["sut_response_latency_ms"] = s2s
            extra["sut_measured_e2e"] = True
        elif extra.get("user_text") and stt is not None and llm is not None and tts is not None:
            turn["sut_response_latency_ms"] = round(float(stt) + float(llm) + float(tts), 1)
            extra["sut_derived_from_components"] = True
        elif llm is not None:
            turn["sut_response_latency_ms"] = llm
            if extra.get("user_text"):
                extra["sut_is_partial_fallback"] = True

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
                turn["extra"]["sut_measured_e2e"] = True
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
                transcript = str(attrs["transcript"])
                if not _is_low_signal_transcript(transcript):
                    _set_turn_text(turn, "user", transcript)
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
    agg: Dict[str, Any] = {}
    for field in (
        "stt_ttfb_ms",
        "llm_ttfb_ms",
        "tts_ttfb_ms",
        "s2s_ttfb_ms",
    ):
        values = [float(t[field]) for t in turns if t.get(field) is not None]
        if values:
            agg[field] = {
                "p50": latency_percentile(values, 50),
                "p90": latency_percentile(values, 90),
                "p95": latency_percentile(values, 95),
                "count": len(values),
            }

    sut_values = response_latency_samples(turns)
    if sut_values:
        agg["sut_response_latency_ms"] = {
            "p50": latency_percentile(sut_values, 50),
            "p90": latency_percentile(sut_values, 90),
            "p95": latency_percentile(sut_values, 95),
            "count": len(sut_values),
        }
    return agg


def _is_eligible_response_latency_sample(turn: Dict[str, Any]) -> bool:
    sut = turn.get("sut_response_latency_ms")
    if sut is None:
        return False
    extra = turn.get("extra") or {}
    if extra.get("user_text"):
        if extra.get("sut_is_partial_fallback"):
            return False
        return True
    if extra.get("sut_measured_e2e"):
        return True
    if not extra.get("assistant_text"):
        return False
    if turn.get("s2s_ttfb_ms") is not None:
        return True
    llm = turn.get("llm_ttfb_ms")
    if llm is None:
        return True
    return abs(float(sut) - float(llm)) > 1.0


def response_latency_samples(turns: List[Dict[str, Any]]) -> List[float]:
    """Collect per-turn SUT samples for header percentiles (TDD §9.3).

    User turns always count. Agent-only turns count when Pipecat measured
    end-to-end latency (turn.user_bot_latency_seconds or s2s), not LLM-TTFB fallback.
    """
    values: List[float] = []
    for turn in turns:
        if not _is_eligible_response_latency_sample(turn):
            continue
        values.append(float(turn["sut_response_latency_ms"]))
    return values


def _response_latency_samples(turns: List[Dict[str, Any]]) -> List[float]:
    return response_latency_samples(turns)


def compute_trace_latency_summary(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute header percentiles and component aggregates from turn rows."""
    aggregates = compute_component_aggregates(turns)
    sut_values = response_latency_samples(turns)
    if not sut_values:
        sut_values = [
            float(t["s2s_ttfb_ms"]) for t in turns if t.get("s2s_ttfb_ms") is not None
        ]
    if not sut_values:
        sut_values = [
            float(t["llm_ttfb_ms"]) for t in turns if t.get("llm_ttfb_ms") is not None
        ]

    return {
        "turn_count": len(turns),
        "response_latency_sample_count": len(sut_values),
        "response_latency_p50_ms": latency_percentile(sut_values, 50),
        "response_latency_p90_ms": latency_percentile(sut_values, 90),
        "response_latency_p95_ms": latency_percentile(sut_values, 95),
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
