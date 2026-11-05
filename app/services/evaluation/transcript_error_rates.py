"""Deterministic transcript WER/CER for call-import evaluations.

User WER / User CER compare production user turns (reference, the
denominator) with diarised user turns (hypothesis). Agent turns are
ignored. ``diarised_speaker_swap`` decides which diarised speaker is
the user.

``normalize_for_wer`` / ``compute_tts_wer_cer`` stay the English TTS path.
"""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.workers.tasks.helpers.script_enforcement import contains_indic_script

NUMBER_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "trillion",
        "point",
        "and",
    }
)
CURRENCY_WORDS = frozenset(
    {
        "dollar",
        "dollars",
        "usd",
        "cent",
        "cents",
        "rupee",
        "rupees",
        "inr",
        "euro",
        "euros",
        "eur",
        "pound",
        "pounds",
        "gbp",
    }
)

DEFAULT_SPEAKER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "user": (
        "user",
        "customer",
        "caller",
        "human",
        "client",
        "patient",
        "speaker 2",
        "speaker2",
    ),
    "agent": (
        "agent",
        "assistant",
        "bot",
        "ai",
        "representative",
        "rep",
        "speaker 1",
        "speaker1",
    ),
}

_SPEAKER_LINE_RE = re.compile(
    r"^\s*(?:\[?[\d:.\s\-]+\]?\s*)?(?P<spk>[A-Za-z][A-Za-z0-9 _]*)\s*[:\-–]\s*(?P<text>.*)$",
)

_CONTRACTIONS = {
    "won't": "will not",
    "can't": "cannot",
    "n't": " not",
    "'re": " are",
    "'ve": " have",
    "'ll": " will",
    "'d": " would",
    "'m": " am",
}


@dataclass(frozen=True)
class ParsedTurns:
    user_text: str
    agent_text: str
    user_turn_count: int
    agent_turn_count: int
    unlabelled: bool


def _normalize_speaker_key(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _resolve_role(
    speaker_label: str,
    aliases: Mapping[str, Tuple[str, ...]],
) -> Optional[str]:
    key = _normalize_speaker_key(speaker_label)
    for role, names in aliases.items():
        for alias in names:
            if key == _normalize_speaker_key(alias):
                return role
    return None


def _is_numeric_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", token))


def normalize_base(text: str) -> str:
    punct_table = str.maketrans("", "", string.punctuation)
    return text.lower().translate(punct_table).strip()


def normalize_entities(text: str) -> str:
    """Collapse numeric/currency spans (English) for WER comparison."""
    tokens = normalize_base(text).split()
    normalized_tokens: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        is_entity_token = (
            _is_numeric_token(token)
            or token in NUMBER_WORDS
            or token in CURRENCY_WORDS
        )
        if not is_entity_token:
            normalized_tokens.append(token)
            i += 1
            continue

        j = i
        has_currency = token in CURRENCY_WORDS
        while j < len(tokens):
            t = tokens[j]
            if _is_numeric_token(t) or t in NUMBER_WORDS or t in CURRENCY_WORDS:
                if t in CURRENCY_WORDS:
                    has_currency = True
                j += 1
                continue
            break

        normalized_tokens.append("<amount>" if has_currency else "<num>")
        i = j

    return " ".join(normalized_tokens)


def normalize_for_wer(text: str) -> str:
    """Primary normalized string for jiwer (lowercase, punctuation, entities)."""
    lowered = text.lower()
    for src, dst in _CONTRACTIONS.items():
        lowered = lowered.replace(src, dst)
    return normalize_entities(lowered)


def parse_labeled_transcript(
    text: str,
    *,
    aliases: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> ParsedTurns:
    alias_map = aliases or DEFAULT_SPEAKER_ALIASES
    raw = (text or "").strip()
    if not raw:
        return ParsedTurns(
            user_text="",
            agent_text="",
            user_turn_count=0,
            agent_turn_count=0,
            unlabelled=True,
        )

    user_parts: List[str] = []
    agent_parts: List[str] = []
    user_turn_count = 0
    agent_turn_count = 0
    saw_label = False
    current_role: Optional[str] = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _SPEAKER_LINE_RE.match(stripped)
        if match:
            role = _resolve_role(match.group("spk"), alias_map)
            turn_text = (match.group("text") or "").strip()
            if role is None:
                if current_role == "user" and turn_text:
                    user_parts.append(turn_text)
                elif current_role == "agent" and turn_text:
                    agent_parts.append(turn_text)
                continue
            saw_label = True
            current_role = role
            if role == "user" and turn_text:
                user_parts.append(turn_text)
                user_turn_count += 1
            elif role == "agent" and turn_text:
                agent_parts.append(turn_text)
                agent_turn_count += 1
            continue

        if current_role == "user":
            user_parts.append(stripped)
        elif current_role == "agent":
            agent_parts.append(stripped)

    return ParsedTurns(
        user_text=" ".join(user_parts).strip(),
        agent_text=" ".join(agent_parts).strip(),
        user_turn_count=user_turn_count,
        agent_turn_count=agent_turn_count,
        unlabelled=not saw_label,
    )


def extract_user_text_from_production(
    text: str,
    *,
    aliases: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> ParsedTurns:
    return parse_labeled_transcript(text, aliases=aliases)


def _effective_diarised_speaker(speaker: str, *, swap: bool) -> str:
    spk = (speaker or "").strip().lower()
    if not swap:
        return spk
    if spk == "agent":
        return "user"
    if spk == "user":
        return "agent"
    return spk


def extract_user_text_from_diarised(
    segments: Optional[Sequence[Mapping[str, Any]]],
    *,
    swap: bool = False,
    diarised_transcript: Optional[str] = None,
    aliases: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> str:
    parts: List[str] = []
    if segments:
        for turn in segments:
            if not isinstance(turn, dict):
                continue
            speaker = _effective_diarised_speaker(
                str(turn.get("speaker") or ""), swap=swap
            )
            text = (turn.get("text") or "").strip()
            if speaker == "user" and text:
                parts.append(text)
        if parts:
            return " ".join(parts).strip()

    if diarised_transcript:
        parsed = parse_labeled_transcript(diarised_transcript, aliases=aliases)
        if not parsed.unlabelled:
            return parsed.user_text
    return " ".join(parts).strip()


def extract_agent_text_from_diarised(
    segments: Optional[Sequence[Mapping[str, Any]]],
    *,
    swap: bool = False,
    diarised_transcript: Optional[str] = None,
    aliases: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> str:
    parts: List[str] = []
    if segments:
        for turn in segments:
            if not isinstance(turn, dict):
                continue
            speaker = _effective_diarised_speaker(
                str(turn.get("speaker") or ""), swap=swap
            )
            text = (turn.get("text") or "").strip()
            if speaker == "agent" and text:
                parts.append(text)
        if parts:
            return " ".join(parts).strip()

    if diarised_transcript:
        parsed = parse_labeled_transcript(diarised_transcript, aliases=aliases)
        if not parsed.unlabelled:
            return parsed.agent_text
    return " ".join(parts).strip()


def _word_counts(text: str) -> int:
    base = normalize_base(text)
    if not base:
        return 0
    return len(base.split())


def compute_user_error_rates(
    reference: str,
    hypothesis: str,
    *,
    agent_reference_for_swap: Optional[str] = None,
    production_user_for_swap: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute WER/CER with diarized user text as reference."""
    ref_raw = (reference or "").strip()
    hyp_raw = (hypothesis or "").strip()

    if not ref_raw:
        return {"skipped": "diarised_user_empty"}

    try:
        from jiwer import cer, process_characters, process_words, wer
    except ImportError:
        return {"skipped": "jiwer_unavailable"}

    ref_base = normalize_base(ref_raw)
    hyp_base = normalize_base(hyp_raw)
    norm_ref = normalize_for_wer(ref_raw)
    norm_hyp = normalize_for_wer(hyp_raw)

    raw_wer = float(wer(ref_base, hyp_base)) if ref_base else 0.0
    raw_cer = float(cer(ref_base, hyp_base)) if ref_base else 0.0
    norm_wer = float(wer(norm_ref, norm_hyp)) if norm_ref else 0.0
    norm_cer = float(cer(norm_ref, norm_hyp)) if norm_ref else 0.0

    word_out = process_words(norm_ref, norm_hyp)
    char_out = process_characters(norm_ref, norm_hyp)

    ref_word_count = _word_counts(norm_ref)
    hyp_word_count = _word_counts(norm_hyp)
    ref_char_count = len(norm_ref.replace(" ", ""))

    chart_wer = min(1.0, norm_wer)
    chart_cer = min(1.0, norm_cer)

    details: Dict[str, Any] = {
        "wer_raw": round(raw_wer, 6),
        "cer_raw": round(raw_cer, 6),
        "wer_true": round(norm_wer, 6),
        "cer_true": round(norm_cer, 6),
        "substitutions": int(word_out.substitutions),
        "deletions": int(word_out.deletions),
        "insertions": int(word_out.insertions),
        "hits": int(word_out.hits),
        "ref_word_count": ref_word_count,
        "hyp_word_count": hyp_word_count,
        "ref_char_count": ref_char_count,
        "reference_preview": ref_raw[:500],
        "hypothesis_preview": hyp_raw[:500],
    }

    if agent_reference_for_swap is not None and production_user_for_swap is not None:
        swap_hyp = (production_user_for_swap or "").strip()
        if swap_hyp and agent_reference_for_swap.strip():
            agent_ref_norm = normalize_for_wer(agent_reference_for_swap)
            swap_hyp_norm = normalize_for_wer(swap_hyp)
            if agent_ref_norm:
                agent_wer = float(wer(agent_ref_norm, swap_hyp_norm))
                if norm_wer > 0 and agent_wer < 0.5 * norm_wer:
                    details["roles_likely_swapped"] = True

    return {
        "wer": round(chart_wer, 6),
        "cer": round(chart_cer, 6),
        "details": details,
    }


def compute_tts_wer_cer(ground_truth: str, predicted: str) -> Dict[str, Any]:
    """TTS/ASR comparison helper (reference = ground truth text)."""
    ref = normalize_base(ground_truth)
    if not ref:
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }
    try:
        from jiwer import cer, wer
    except ImportError:
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }

    hyp = normalize_base(predicted)
    raw_wer = round(float(wer(ref, hyp)), 4)
    raw_cer = round(float(cer(ref, hyp)), 4)
    norm_ref = normalize_entities(ground_truth)
    norm_hyp = normalize_entities(predicted)
    normalized_wer = round(float(wer(norm_ref, norm_hyp)), 4) if norm_ref else None
    normalized_cer = round(float(cer(norm_ref, norm_hyp)), 4) if norm_ref else None
    return {
        "raw_wer": raw_wer,
        "raw_cer": raw_cer,
        "normalized_wer": normalized_wer,
        "normalized_cer": normalized_cer,
    }


_ZW_CHARS = "\u200c\u200d"
_INDIC_PUNCT = "।॥"
_FILLER_TOKENS = frozenset(
    {"hmm", "haan", "umm", "uh", "achha", "हम्म", "हाँ", "हां"}
)
_SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(?:\[?\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\]?\s*)?"
    r"(?P<spk>[A-Za-z][A-Za-z0-9 _]*?)\s*[:\-–]\s*(?P<text>.*)$"
)
_LEADING_TIMESTAMP_RE = re.compile(
    r"^\s*\[?\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\]?\s*"
)
_INDEPENDENT_VOWELS = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
}
_MATRAS = {
    "ा": "aa",
    "ि": "i",
    "ी": "ee",
    "ु": "u",
    "ू": "oo",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
}
_CONSONANTS = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
    "ळ": "l",
    "क़": "k",
    "ख़": "kh",
    "ग़": "g",
    "ज़": "j",
    "ड़": "d",
    "ढ़": "dh",
    "फ़": "ph",
    "य़": "y",
}
_NUKTA_BASE = {
    "क़": "क",
    "ख़": "ख",
    "ग़": "ग",
    "ज़": "ज",
    "ड़": "ड",
    "ढ़": "ढ",
    "फ़": "फ",
    "य़": "य",
}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_VIRAMA = "\u094d"
_ANUSVARA = "\u0902"
_NUKTA = "\u093c"


def _fold_devanagari(text: str) -> str:
    folded = text
    for src, dst in _NUKTA_BASE.items():
        folded = folded.replace(src, dst)
    return folded.replace("ँ", "ं").translate(_DEVANAGARI_DIGITS)


def transliterate_devanagari_to_latin(text: str) -> str:
    """Minimal Devanagari to Latin. Other characters pass through."""
    chars = list(_fold_devanagari(unicodedata.normalize("NFC", text or "")))
    out: List[str] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        if char in _CONSONANTS:
            consonant = _CONSONANTS[char]
            index += 1
            if index < len(chars) and chars[index] == _NUKTA:
                index += 1
            vowel = "a"
            if index < len(chars) and chars[index] == _VIRAMA:
                vowel = ""
                index += 1
            elif index < len(chars) and chars[index] in _MATRAS:
                vowel = _MATRAS[chars[index]]
                index += 1
            out.append(consonant + vowel)
            if index < len(chars) and chars[index] == _ANUSVARA:
                out.append("n")
                index += 1
            continue
        if char in _INDEPENDENT_VOWELS:
            out.append(_INDEPENDENT_VOWELS[char])
            index += 1
            if index < len(chars) and chars[index] == _ANUSVARA:
                out.append("n")
                index += 1
            continue
        if char == _ANUSVARA:
            out.append("n")
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _strip_speaker_prefixes(text: str) -> str:
    lines: List[str] = []
    for line in (text or "").splitlines():
        match = _SPEAKER_PREFIX_RE.match(line.strip())
        if match:
            kept = (match.group("text") or "").strip()
            if kept:
                lines.append(kept)
            continue
        stripped = _LEADING_TIMESTAMP_RE.sub("", line.strip())
        if stripped:
            lines.append(stripped)
    return " ".join(lines)


def _fold_romanised_token(token: str) -> str:
    folded = token.replace("th", "t").replace("dh", "d")
    previous = None
    while folded != previous:
        previous = folded
        folded = folded.replace("aa", "a").replace("ee", "i").replace("oo", "u")
    folded = folded.replace("w", "v")
    folded = re.sub(r"(.)\1+", r"\1", folded)
    if len(folded) > 1 and folded.endswith("h"):
        folded = folded[:-1]
    return folded


def normalise_for_error_rate(text: str, *, romanised: bool) -> str:
    """Normalise one side of a production-vs-diarised comparison."""
    cleaned = _strip_speaker_prefixes(unicodedata.normalize("NFC", text or ""))
    cleaned = _fold_devanagari(cleaned.lower())
    punct = string.punctuation + _INDIC_PUNCT + _ZW_CHARS
    cleaned = cleaned.translate(str.maketrans("", "", punct))
    tokens = [token for token in cleaned.split() if token not in _FILLER_TOKENS]
    if romanised:
        tokens = [_fold_romanised_token(token) for token in tokens]
        tokens = [token for token in tokens if token and token not in _FILLER_TOKENS]
    return " ".join(tokens)


def _rate(distance: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(distance / denominator, 4)


def compute_transcript_error_rates(
    reference: str,
    hypothesis: str,
    *,
    mode: str,
    script_mismatch: bool,
) -> Dict[str, Any]:
    """Score diarised user text against production user text.

    ``reference`` is the production user turns (the denominator).
    ``hypothesis`` is the diarised user turns. Rates are ``None`` when
    production user text is empty after normalisation. A non-empty
    reference with an empty hypothesis scores 1.0.
    """
    romanised = mode == "romanised_fallback"
    norm_ref = normalise_for_error_rate(reference or "", romanised=romanised)
    norm_hyp = normalise_for_error_rate(hypothesis or "", romanised=romanised)
    ref_words = norm_ref.split() if norm_ref else []
    hyp_words = norm_hyp.split() if norm_hyp else []
    ref_chars = norm_ref.replace(" ", "")
    hyp_chars = norm_hyp.replace(" ", "")
    if not ref_words and not ref_chars:
        return {
            "cer": None,
            "wer": None,
            "mode": mode,
            "script_mismatch": script_mismatch,
            "ref_chars": 0,
            "ref_words": 0,
            "hyp_words": len(hyp_words),
            "char_distance": 0,
            "word_distance": 0,
        }

    from rapidfuzz.distance import Levenshtein

    word_distance = int(Levenshtein.distance(ref_words, hyp_words))
    char_distance = int(Levenshtein.distance(ref_chars, hyp_chars))
    return {
        "cer": _rate(char_distance, len(ref_chars)),
        "wer": _rate(word_distance, len(ref_words)),
        "mode": mode,
        "script_mismatch": script_mismatch,
        "ref_chars": len(ref_chars),
        "ref_words": len(ref_words),
        "hyp_words": len(hyp_words),
        "char_distance": char_distance,
        "word_distance": word_distance,
    }


def _aliases_for_user_turns(
    custom: Optional[Mapping[str, Tuple[str, ...]]],
) -> Dict[str, Tuple[str, ...]]:
    """Default user/agent names, plus any extra names stored on the import."""
    merged = {
        role: tuple(names) for role, names in DEFAULT_SPEAKER_ALIASES.items()
    }
    if not isinstance(custom, dict):
        return merged
    for role, names in custom.items():
        key = str(role or "").strip().lower()
        if key not in merged or isinstance(names, str) or not isinstance(names, Sequence):
            continue
        extra = tuple(str(name).strip() for name in names if str(name).strip())
        merged[key] = tuple(dict.fromkeys((*merged[key], *extra)))
    return merged


def _user_hypothesis_from_diarised(
    segments: Optional[Sequence[Mapping[str, Any]]],
    diarised_transcript: str,
    *,
    swap: bool,
    aliases: Mapping[str, Tuple[str, ...]],
) -> Tuple[str, bool]:
    """Return diarised user text and whether any selected turn used ``text_native``.

    Segments win over the rendered transcript. The full STT string is not
    used: it includes agent speech. A user turn without ``text_native``
    keeps that turn's romanised ``text``.
    """
    if segments:
        parts: List[str] = []
        used_native = False
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            speaker = _effective_diarised_speaker(
                str(segment.get("speaker") or ""),
                swap=swap,
            )
            if _resolve_role(speaker, aliases) != "user":
                continue
            native = str(segment.get("text_native") or "").strip()
            text = str(segment.get("text") or "").strip()
            if native:
                used_native = True
                parts.append(native)
            elif text:
                parts.append(text)
        return " ".join(parts).strip(), used_native

    parsed = parse_labeled_transcript(diarised_transcript or "", aliases=aliases)
    if parsed.unlabelled:
        return "", False
    return parsed.user_text, False


def select_comparison_texts(
    *,
    production_transcript: str,
    diarised_transcript: str = "",
    diarised_segments: Optional[Sequence[Mapping[str, Any]]] = None,
    diarised_native_transcript: Optional[str] = None,
    diarised_speaker_swap: bool = False,
    speaker_aliases: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> Dict[str, Any]:
    """Pick production user turns and diarised user turns.

    Agent turns are dropped on both sides. ``diarised_speaker_swap``
    flips which diarised speaker is the user. Native mode uses
    ``text_native`` on those user turns. The full
    ``diarised_native_transcript`` is ignored because it includes the
    agent. The romanised fallback transliterates Indic production user
    text when no native user hypothesis exists.
    """
    del diarised_native_transcript  # full-call STT; agent speech included
    aliases = _aliases_for_user_turns(speaker_aliases)
    production_user = extract_user_text_from_production(
        production_transcript or "",
        aliases=aliases,
    )
    reference_raw = "" if production_user.unlabelled else production_user.user_text
    hypothesis, has_native_hypothesis = _user_hypothesis_from_diarised(
        diarised_segments,
        diarised_transcript or "",
        swap=diarised_speaker_swap,
        aliases=aliases,
    )
    script_mismatch = contains_indic_script(reference_raw) != contains_indic_script(
        hypothesis
    )
    reference = reference_raw
    mode = "native"
    # Romanise only when the hypothesis is not already in the reference
    # script. A diariser can return the same Indic sentence in ``text``
    # with no ``text_native``; converting only the reference would score
    # matching speech as a large error.
    if (
        not has_native_hypothesis
        and contains_indic_script(reference_raw)
        and not contains_indic_script(hypothesis)
    ):
        reference = transliterate_devanagari_to_latin(reference_raw)
        mode = "romanised_fallback"
    return {
        "reference": reference,
        "hypothesis": hypothesis,
        "mode": mode,
        "script_mismatch": script_mismatch,
    }


def build_word_alignment(
    reference: str,
    hypothesis: str,
    *,
    romanised: bool = False,
) -> Dict[str, Any]:
    """On-demand word alignment for the production-vs-diarised diff."""
    norm_ref = normalise_for_error_rate(reference or "", romanised=romanised)
    norm_hyp = normalise_for_error_rate(hypothesis or "", romanised=romanised)
    ref_tokens = norm_ref.split() if norm_ref else []
    hyp_tokens = norm_hyp.split() if norm_hyp else []
    if not ref_tokens:
        return {
            "reference": [],
            "hypothesis": hyp_tokens,
            "chunks": [],
            "substitutions": 0,
            "deletions": 0,
            "insertions": 0,
            "hits": 0,
            "wer": 0.0,
        }
    from rapidfuzz.distance import Levenshtein

    chunks = []
    substitutions = deletions = insertions = hits = 0
    for opcode in Levenshtein.opcodes(ref_tokens, hyp_tokens):
        kind = {
            "equal": "equal",
            "replace": "substitute",
            "delete": "delete",
            "insert": "insert",
        }.get(opcode.tag, opcode.tag)
        if kind == "equal":
            hits += opcode.src_end - opcode.src_start
        elif kind == "substitute":
            substitutions += max(
                opcode.src_end - opcode.src_start,
                opcode.dest_end - opcode.dest_start,
            )
        elif kind == "delete":
            deletions += opcode.src_end - opcode.src_start
        elif kind == "insert":
            insertions += opcode.dest_end - opcode.dest_start
        chunks.append(
            {
                "type": kind,
                "ref_start_idx": opcode.src_start,
                "ref_end_idx": opcode.src_end,
                "hyp_start_idx": opcode.dest_start,
                "hyp_end_idx": opcode.dest_end,
            }
        )
    word_distance = int(Levenshtein.distance(ref_tokens, hyp_tokens))
    return {
        "reference": ref_tokens,
        "hypothesis": hyp_tokens,
        "chunks": chunks,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "hits": hits,
        "wer": round(word_distance / len(ref_tokens), 4),
    }


