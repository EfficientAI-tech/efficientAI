#!/usr/bin/env python3
"""Generate app/config/pricing_catalog.json from models.json + LiteLLM model_cost."""

from __future__ import annotations

import argparse
import json
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_JSON = REPO_ROOT / "app" / "config" / "models.json"
MANUAL_JSON = REPO_ROOT / "app" / "config" / "pricing_manual.json"
OUTPUT_JSON = REPO_ROOT / "app" / "config" / "pricing_catalog.json"

LITELLM_PROVIDER_PREFIX = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",
    "azure": "azure",
    "aws": "bedrock",
    "deepseek": "deepseek",
    "groq": "groq",
    "xai": "xai",
    "fireworks": "fireworks_ai",
    "sarvam": "sarvam",
    "deepgram": "deepgram",
    "elevenlabs": "elevenlabs",
    "cartesia": "cartesia",
}

# Catalog key -> LiteLLM model_cost key (when auto-resolution fails).
EXPLICIT_LITELLM_KEYS: Dict[str, str] = {
    "chat-latest": "gpt-5-chat-latest",
    "azure-openai-gpt4": "gpt-4",
    "aws-bedrock-claude": "anthropic.claude-sonnet-4-20250514-v1:0",
    "aws-transcribe": "whisper-1",
    "aws-polly": "aws_polly/neural",
    "google-speech-v2": "gemini-2.5-flash",
    "gemini-2.5-pro-stt": "gemini-2.5-flash",
    "gemini-2.5-flash-stt": "gemini-2.5-flash",
    "gemini-2.5-flash-lite-stt": "gemini-2.5-flash-lite",
    "azure-speech-v1": "azure/speech/azure-stt",
    "azure-tts-v1": "azure/speech/azure-tts",
    "pulse-v4": "whisper-1",
    "deepgram-flux": "deepgram/nova-3",
    "deepgram-nova-3-general-preview-12-2025": "deepgram/nova-3-general",
    "minimax-m2p5": "fireworks_ai/minimax-m2p7",
    "qwen3p6-plus": "openrouter/qwen/qwen3.6-plus",
    "grok-build-0.1": "xai/grok-3",
    "grok-4.20-0309-non-reasoning": "xai/grok-4-fast-non-reasoning",
    "grok-4.20-multi-agent-0309": "xai/grok-4",
    # ElevenLabs: LiteLLM only prices a subset; map siblings to closest priced SKU.
    "scribe_v2": "elevenlabs/scribe_v1",
    "scribe_v2_realtime": "elevenlabs/scribe_v1",
    "eleven_flash_v2_5": "elevenlabs/eleven_multilingual_v2",
    "eleven_turbo_v2_5": "elevenlabs/eleven_multilingual_v2",
    "eleven_ttv_v3": "elevenlabs/eleven_v3",
    "eleven_multilingual_ttv_v2": "elevenlabs/eleven_multilingual_v2",
    "eleven_english_sts_v2": "elevenlabs/eleven_multilingual_v2",
    "eleven_multilingual_sts_v2": "elevenlabs/eleven_multilingual_v2",
    "eleven_text_to_sound_v2": "elevenlabs/eleven_multilingual_v2",
    "music_v1": "elevenlabs/eleven_multilingual_v2",
}

MICRO_USD_PER_USD = 1_000_000


def _azure_deployment_name(catalog_model: str) -> str:
    if catalog_model == "azure-openai-gpt4":
        return "gpt-4"
    if catalog_model.startswith("azure-"):
        return catalog_model[len("azure-") :]
    return catalog_model


def _usage_kind(model_type: Optional[str]) -> str:
    if model_type == "stt":
        return "stt"
    if model_type in {"tts", "sts", "sound_effects", "music"}:
        return "tts"
    return "llm"


def _fireworks_model(name: str) -> str:
    if name.startswith("accounts/"):
        return name
    return f"accounts/fireworks/models/{name}"


def _per_million_micro_usd(cost_per_unit: float) -> int:
    return int(round(float(cost_per_unit) * MICRO_USD_PER_USD * 1_000_000))


def _per_second_micro_usd(cost_per_second: float) -> int:
    return int(round(float(cost_per_second) * MICRO_USD_PER_USD))


def _first_cost(info: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = info.get(key)
        if value is not None and float(value) > 0:
            return float(value)
    return 0.0


def _litellm_candidates(
    catalog_name: str, provider: str, model_type: str
) -> List[str]:
    if catalog_name in EXPLICIT_LITELLM_KEYS:
        return [EXPLICIT_LITELLM_KEYS[catalog_name]]

    prefix = LITELLM_PROVIDER_PREFIX.get(provider, provider)
    candidates: List[str] = []

    if provider == "azure" and model_type == "llm":
        deployment = _azure_deployment_name(catalog_name)
        candidates.extend(
            [
                f"azure/{deployment}",
                f"openai/{deployment}",
                deployment,
            ]
        )
    elif provider == "azure" and model_type == "stt":
        candidates.extend(["azure/speech/azure-stt", f"azure/{catalog_name}"])
    elif provider == "azure" and model_type == "tts":
        candidates.extend(["azure/speech/azure-tts", f"azure/{catalog_name}"])
    elif provider == "deepgram":
        stripped = (
            catalog_name[len("deepgram-") :]
            if catalog_name.startswith("deepgram-")
            else catalog_name
        )
        candidates.extend([f"deepgram/{stripped}", stripped])
    elif provider == "fireworks" and model_type == "llm":
        fw = _fireworks_model(catalog_name)
        candidates.extend(
            [
                f"fireworks_ai/{fw}",
                f"fireworks_ai/{catalog_name}",
                f"fireworks_ai/accounts/fireworks/models/{catalog_name}",
                catalog_name,
            ]
        )
    elif provider == "elevenlabs":
        candidates.extend([f"elevenlabs/{catalog_name}", catalog_name])
    elif provider == "google" and catalog_name.endswith("-stt"):
        base = catalog_name[: -len("-stt")]
        candidates.extend([base, f"gemini/{base}"])
    else:
        candidates.extend([catalog_name, f"{prefix}/{catalog_name}"])

    # De-dupe while preserving order.
    seen = set()
    ordered: List[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _resolve_litellm_key(
    catalog_name: str,
    provider: str,
    model_type: str,
    model_cost: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    for key in _litellm_candidates(catalog_name, provider, model_type):
        info = model_cost.get(key)
        if not info:
            continue
        if any("cost" in field and info.get(field) for field in info):
            return key, info

    for key, info in model_cost.items():
        if key == "sample_spec":
            continue
        if key.endswith(f"/{catalog_name}") or key == catalog_name:
            if any("cost" in field and info.get(field) for field in info):
                return key, info
    return None, None


def _convert_litellm_pricing(
    info: Dict[str, Any], *, usage_kind: str
) -> Dict[str, int]:
    entry: Dict[str, int] = {
        "input_micro_usd_per_million": 0,
        "output_micro_usd_per_million": 0,
        "cache_read_micro_usd_per_million": 0,
        "cache_creation_micro_usd_per_million": 0,
        "reasoning_micro_usd_per_million": 0,
        "audio_micro_usd_per_second": 0,
        "tts_micro_usd_per_million_chars": 0,
    }

    if usage_kind == "stt":
        audio = _first_cost(
            info,
            "input_cost_per_second",
            "output_cost_per_second",
        )
        if not audio:
            audio_token = _first_cost(info, "input_cost_per_audio_token")
            if audio_token:
                # LiteLLM audio-token STT models: ~25 audio tokens/sec (OpenAI convention).
                audio = audio_token * 25.0
        entry["audio_micro_usd_per_second"] = _per_second_micro_usd(audio)
        return entry

    if usage_kind == "tts":
        per_char = _first_cost(
            info,
            "input_cost_per_character",
            "output_cost_per_character",
        )
        if per_char:
            entry["tts_micro_usd_per_million_chars"] = _per_million_micro_usd(per_char)
            return entry
        per_token = _first_cost(
            info,
            "output_cost_per_token",
            "input_cost_per_token",
        )
        if per_token:
            # Approximate chars/token ~= 4 when LiteLLM only exposes token pricing.
            entry["tts_micro_usd_per_million_chars"] = _per_million_micro_usd(
                per_token / 4.0
            )
        return entry

    entry["input_micro_usd_per_million"] = _per_million_micro_usd(
        _first_cost(info, "input_cost_per_token", "input_cost_per_audio_token")
    )
    entry["output_micro_usd_per_million"] = _per_million_micro_usd(
        _first_cost(info, "output_cost_per_token")
    )
    entry["cache_read_micro_usd_per_million"] = _per_million_micro_usd(
        _first_cost(info, "cache_read_input_token_cost")
    )
    entry["cache_creation_micro_usd_per_million"] = _per_million_micro_usd(
        _first_cost(info, "cache_creation_input_token_cost")
    )
    entry["reasoning_micro_usd_per_million"] = _per_million_micro_usd(
        _first_cost(info, "output_cost_per_reasoning_token")
    )
    return entry


def _load_model_cost(*, remote: bool) -> Dict[str, Dict[str, Any]]:
    if remote:
        from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map

        return get_model_cost_map(
            url="https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
        )
    from litellm import model_cost

    return dict(model_cost)


def _load_manual_entries() -> Dict[str, Dict[str, Any]]:
    if not MANUAL_JSON.exists():
        return {}
    try:
        payload = json.loads(MANUAL_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if not key.startswith("_") and isinstance(value, dict)
    }


def _apply_manual_entries(
    catalog: Dict[str, Any], meta: Dict[str, Any], models: Dict[str, Any]
) -> None:
    manual = _load_manual_entries()
    if not manual:
        return
    meta.setdefault("manual", {})
    for catalog_name, entry in manual.items():
        if catalog_name in catalog:
            continue
        if catalog_name not in models or catalog_name.startswith("_"):
            continue
        model_type = str(models[catalog_name].get("model_type") or "llm")
        usage_kind = entry.get("usage_kind") or _usage_kind(model_type)
        pricing = {
            k: int(v)
            for k, v in entry.items()
            if k != "usage_kind" and not k.startswith("_") and v is not None
        }
        if not any(pricing.values()):
            continue
        catalog[catalog_name] = {
            "usage_kind": usage_kind,
            **pricing,
            "_price_source": entry.get("_price_source", "pricing_manual.json"),
            "_litellm_proxy": True,
        }
        meta["manual"][catalog_name] = entry.get("_price_source", "pricing_manual.json")
        meta["resolved"][catalog_name] = "manual"
        meta["unresolved"] = [
            item for item in meta["unresolved"] if item.get("model") != catalog_name
        ]


def build_catalog(*, remote: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    model_cost = _load_model_cost(remote=remote)

    catalog: Dict[str, Any] = {}
    meta: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "litellm_remote" if remote else "litellm_local",
        "resolved": {},
        "unresolved": [],
    }

    for catalog_name, cfg in sorted(models.items()):
        if catalog_name.startswith("_") or not isinstance(cfg, dict):
            continue
        provider = str(cfg.get("provider") or "")
        model_type = str(cfg.get("model_type") or "llm")
        usage_kind = _usage_kind(model_type)

        litellm_key, info = _resolve_litellm_key(
            catalog_name, provider, model_type, model_cost
        )
        if not info:
            meta["unresolved"].append(
                {
                    "model": catalog_name,
                    "provider": provider,
                    "model_type": model_type,
                }
            )
            continue

        pricing = _convert_litellm_pricing(info, usage_kind=usage_kind)
        if not any(pricing.values()):
            meta["unresolved"].append(
                {
                    "model": catalog_name,
                    "provider": provider,
                    "model_type": model_type,
                    "litellm_key": litellm_key,
                    "reason": "zero_cost",
                }
            )
            continue

        catalog[catalog_name] = {
            "usage_kind": usage_kind,
            **pricing,
            "_litellm_key": litellm_key,
            "_litellm_proxy": catalog_name not in {litellm_key, litellm_key.split("/")[-1]},
        }
        meta["resolved"][catalog_name] = litellm_key

    _apply_manual_entries(catalog, meta, models)
    catalog["_metadata"] = meta
    return catalog, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use bundled LiteLLM model_cost instead of fetching remote JSON",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of writing pricing_catalog.json",
    )
    parser.add_argument(
        "--write-models",
        action="store_true",
        help="Also merge plan-format pricing blocks into app/config/models.json",
    )
    args = parser.parse_args()

    catalog, meta = build_catalog(remote=not args.local)
    payload = json.dumps(catalog, indent=2, sort_keys=True) + "\n"
    if args.stdout:
        sys.stdout.write(payload)
    else:
        OUTPUT_JSON.write_text(payload, encoding="utf-8")

    if args.write_models:
        merge_path = REPO_ROOT / "scripts" / "merge_pricing_into_models_json.py"
        spec = importlib.util.spec_from_file_location(
            "merge_pricing_into_models_json", merge_path
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        updated, skipped = module.merge()
        print(
            f"models.json pricing: {updated} updated, {skipped} skipped",
            file=sys.stderr,
        )

    resolved = len(meta["resolved"])
    unresolved = len(meta["unresolved"])
    print(
        f"pricing catalog: {resolved} resolved, {unresolved} unresolved -> {OUTPUT_JSON if not args.stdout else 'stdout'}",
        file=sys.stderr,
    )
    if unresolved:
        for item in meta["unresolved"]:
            print(f"  unresolved: {item['model']} ({item.get('reason', 'no_litellm_match')})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
