"""Celery tasks: TTS comparison generation and evaluation."""

import os
import re
import string
import tempfile
from typing import Any, Dict
from uuid import UUID

import numpy as np
from loguru import logger

from app.database import SessionLocal

from app.workers.config import celery_app


def _sanitize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Convert numpy scalars to native Python types so the dict is JSON-serializable."""
    out: Dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, (np.floating, np.float32, np.float64)):
            out[key] = float(value)
        elif isinstance(value, (np.integer, np.int32, np.int64)):
            out[key] = int(value)
        elif isinstance(value, np.ndarray):
            out[key] = value.tolist()
        elif isinstance(value, np.bool_):
            out[key] = bool(value)
        else:
            out[key] = value
    return out


def _compute_wer_cer(ground_truth: str, predicted: str):
    """Compute raw and normalized WER/CER between reference and ASR text.

    Normalized scores reduce false penalties on numeric/currency phrasing
    differences (for example "$1,234.56" vs "one thousand two hundred...").
    """
    try:
        from jiwer import cer, wer
    except ImportError:
        logger.warning("[TTS Eval] jiwer not installed – skipping WER/CER")
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }

    number_words = {
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
        "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
        "billion", "trillion", "point", "and",
    }
    currency_words = {
        "dollar", "dollars", "usd", "cent", "cents", "rupee", "rupees", "inr",
        "euro", "euros", "eur", "pound", "pounds", "gbp",
    }

    def _is_numeric_token(token: str) -> bool:
        return bool(re.fullmatch(r"\d+(?:\.\d+)?", token))

    def _normalize_base(text: str) -> str:
        punct_table = str.maketrans("", "", string.punctuation)
        return text.lower().translate(punct_table).strip()

    def _normalize_entities(text: str) -> str:
        tokens = _normalize_base(text).split()
        normalized_tokens = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            is_entity_token = (
                _is_numeric_token(token)
                or token in number_words
                or token in currency_words
            )
            if not is_entity_token:
                normalized_tokens.append(token)
                i += 1
                continue

            j = i
            has_currency = token in currency_words
            while j < len(tokens):
                t = tokens[j]
                if _is_numeric_token(t) or t in number_words or t in currency_words:
                    if t in currency_words:
                        has_currency = True
                    j += 1
                    continue
                break

            normalized_tokens.append("<amount>" if has_currency else "<num>")
            i = j

        return " ".join(normalized_tokens)

    ref = _normalize_base(ground_truth)
    hyp = _normalize_base(predicted)

    if not ref:
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }

    try:
        raw_wer = round(wer(ref, hyp), 4)
        raw_cer = round(cer(ref, hyp), 4)

        norm_ref = _normalize_entities(ground_truth)
        norm_hyp = _normalize_entities(predicted)
        normalized_wer = round(wer(norm_ref, norm_hyp), 4) if norm_ref else None
        normalized_cer = round(cer(norm_ref, norm_hyp), 4) if norm_ref else None

        return {
            "raw_wer": raw_wer,
            "raw_cer": raw_cer,
            "normalized_wer": normalized_wer,
            "normalized_cer": normalized_cer,
        }
    except Exception as e:
        logger.warning(f"[TTS Eval] WER/CER calculation error: {e}")
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }


def _resolve_stt_config(comp, db) -> tuple:
    """Resolve STT provider/model for WER/CER evaluation.

    Priority:
      1. Per-comparison override (comp.eval_stt_provider / eval_stt_model)
      2. First Voice Bundle in the org that has STT configured
      3. (None, None) – WER/CER will be skipped
    """
    if getattr(comp, "eval_stt_provider", None) and getattr(comp, "eval_stt_model", None):
        return comp.eval_stt_provider, comp.eval_stt_model

    from app.models.database import VoiceBundle

    bundle = (
        db.query(VoiceBundle)
        .filter(
            VoiceBundle.organization_id == comp.organization_id,
            VoiceBundle.stt_provider.isnot(None),
            VoiceBundle.stt_model.isnot(None),
        )
        .order_by(VoiceBundle.created_at)
        .first()
    )
    if bundle:
        return bundle.stt_provider, bundle.stt_model

    return None, None


@celery_app.task(name="generate_tts_comparison", bind=True, max_retries=1)
def generate_tts_comparison_task(self, comparison_id: str):
    """
    Generate TTS audio for every sample in a comparison, upload to S3,
    then dispatch evaluation.
    """
    from app.models.database import (
        TTSComparison,
        TTSSample,
        TTSComparisonStatus,
        TTSSampleStatus,
        ModelProvider,
    )
    from app.services.ai.tts_service import tts_service, get_audio_file_extension
    from app.services.storage.s3_service import s3_service

    db = SessionLocal()
    try:
        comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
        if not comp:
            logger.error(f"[TTS Generate] Comparison {comparison_id} not found")
            return {"error": "not found"}

        comp.status = TTSComparisonStatus.GENERATING.value
        db.commit()

        # blind_test_only comparisons have no TTS to synthesize – the API
        # already pre-resolved every sample's audio_s3_key and marked them
        # COMPLETED. Just transition to evaluation (which will also be a
        # mostly-no-op for non-tts audio) and return.
        if (getattr(comp, "mode", "benchmark") or "benchmark") == "blind_test_only":
            comp.status = TTSComparisonStatus.COMPLETED.value
            db.commit()
            return {"skipped": "blind_test_only"}

        samples = (
            db.query(TTSSample)
            .filter(TTSSample.comparison_id == comp.id)
            .order_by(TTSSample.sample_index)
            .all()
        )

        voice_configs_a = {v["id"]: v for v in (comp.voices_a or []) if isinstance(v, dict)}
        voice_configs_b = {v["id"]: v for v in (comp.voices_b or []) if isinstance(v, dict)}

        def _resolve_voice_meta(sample_obj):
            """Match sample to correct side's voice config (A or B)."""
            if sample_obj.side == "A":
                return voice_configs_a.get(sample_obj.voice_id) or {}
            if sample_obj.side == "B":
                return voice_configs_b.get(sample_obj.voice_id) or {}
            is_side_a = (
                sample_obj.provider == comp.provider_a and sample_obj.model == comp.model_a
            )
            is_side_b = (
                sample_obj.provider == comp.provider_b and sample_obj.model == comp.model_b
            )
            if is_side_a and not is_side_b:
                return voice_configs_a.get(sample_obj.voice_id) or {}
            if is_side_b and not is_side_a:
                return voice_configs_b.get(sample_obj.voice_id) or {}
            return voice_configs_a.get(sample_obj.voice_id) or voice_configs_b.get(sample_obj.voice_id) or {}

        failed_count = 0
        for sample in samples:
            # Recording / upload samples were pre-resolved at create time and
            # already have an audio_s3_key + COMPLETED status. Don't re-run
            # synthesis on them – just leave them alone so the evaluation
            # phase can pick them up alongside any TTS-generated audio.
            if (getattr(sample, "source_type", "tts") or "tts") != "tts":
                if sample.status != TTSSampleStatus.COMPLETED.value:
                    sample.status = TTSSampleStatus.COMPLETED.value
                    db.commit()
                continue
            try:
                sample.status = TTSSampleStatus.GENERATING.value
                db.commit()

                voice_meta = _resolve_voice_meta(sample)
                tts_config = {}
                sample_rate_hz = voice_meta.get("sample_rate_hz")
                if sample_rate_hz:
                    tts_config["sample_rate_hz"] = int(sample_rate_hz)
                language_code = voice_meta.get("language_code")
                if language_code:
                    tts_config["language_code"] = language_code

                provider_enum = ModelProvider(sample.provider)
                logger.info(
                    f"[TTS Generate] Sample {sample.id} – "
                    f"provider={sample.provider} voice={sample.voice_id} "
                    f"sample_rate_hz={sample_rate_hz} config={tts_config}"
                )
                audio_bytes, latency_ms, ttfb_ms = tts_service.synthesize_timed(
                    text=sample.text,
                    tts_provider=provider_enum,
                    tts_model=sample.model,
                    organization_id=comp.organization_id,
                    db=db,
                    voice=sample.voice_id,
                    config=tts_config or None,
                )

                audio_ext = get_audio_file_extension(
                    sample.provider, int(sample_rate_hz) if sample_rate_hz else None
                )
                s3_key = s3_service.upload_file_by_key(
                    file_content=audio_bytes,
                    key=f"{s3_service.prefix}organizations/{comp.organization_id}/voicePlayground/{comp.id}/{sample.id}.{audio_ext}",
                )

                if audio_ext == "wav" and len(audio_bytes) > 44:
                    import struct as _struct

                    sr = _struct.unpack_from("<I", audio_bytes, 24)[0]
                    duration_est = (len(audio_bytes) - 44) / (2 * sr) if sr > 0 else None
                else:
                    duration_est = len(audio_bytes) / (128000 / 8) if audio_bytes else None

                sample.audio_s3_key = s3_key
                sample.latency_ms = round(latency_ms, 1)
                sample.ttfb_ms = round(ttfb_ms, 1)
                sample.duration_seconds = round(duration_est, 2) if duration_est else None
                sample.status = TTSSampleStatus.COMPLETED.value
                db.commit()

                logger.info(
                    f"[TTS Generate] Sample {sample.id} done – "
                    f"{sample.provider}/{sample.voice_name} ttfb={ttfb_ms:.0f}ms total={latency_ms:.0f}ms"
                )

            except Exception as e:
                logger.error("[TTS Generate] Sample {} failed: {}", sample.id, e)
                sample.status = TTSSampleStatus.FAILED.value
                sample.error_message = str(e)[:500]
                db.commit()
                failed_count += 1

        total = len(samples)
        tts_samples = sum(
            1 for s in samples if (getattr(s, "source_type", "tts") or "tts") == "tts"
        )
        if tts_samples > 0 and failed_count == tts_samples:
            comp.status = TTSComparisonStatus.FAILED.value
            comp.error_message = "All samples failed to generate"
            db.commit()
            return {"error": "all failed"}

        comp.status = TTSComparisonStatus.EVALUATING.value
        db.commit()
        evaluate_tts_comparison_task.delay(comparison_id)

        return {"generated": total - failed_count, "failed": failed_count}

    except Exception as exc:
        logger.error("[TTS Generate] Task failed: {}", exc, exc_info=True)
        try:
            comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
            if comp:
                comp.status = TTSComparisonStatus.FAILED.value
                comp.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


@celery_app.task(name="evaluate_tts_comparison", bind=True, max_retries=1)
def evaluate_tts_comparison_task(self, comparison_id: str):
    """
    Download each completed sample from S3 and run qualitative voice
    metrics (MOS, Valence, Arousal, Prosody) plus ASR-based WER/CER
    for hallucination detection.
    """
    from app.models.database import (
        TTSComparison,
        TTSSample,
        TTSComparisonStatus,
        TTSSampleStatus,
        ModelProvider,
    )
    from app.services.storage.s3_service import s3_service
    from app.services.audio.qualitative_voice_service import qualitative_voice_service
    from app.services.ai.transcription_service import transcription_service

    db = SessionLocal()
    try:
        comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
        if not comp:
            return {"error": "not found"}

        samples = (
            db.query(TTSSample)
            .filter(
                TTSSample.comparison_id == comp.id,
                TTSSample.status == TTSSampleStatus.COMPLETED.value,
                TTSSample.audio_s3_key.isnot(None),
            )
            .all()
        )

        if not samples:
            comp.status = TTSComparisonStatus.COMPLETED.value
            db.commit()
            return {"evaluated": 0}

        stt_provider_str, stt_model = _resolve_stt_config(comp, db)
        stt_available = bool(stt_provider_str and stt_model)
        if stt_available:
            logger.info(f"[TTS Eval] Using STT provider {stt_provider_str}/{stt_model} for WER/CER")
        else:
            logger.warning(
                "[TTS Eval] No STT provider configured (check comparison settings or Voice Bundles) "
                "– WER/CER metrics will be skipped"
            )

        evaluated = 0
        for sample in samples:
            tmp_path = None
            try:
                audio_bytes = s3_service.download_file_by_key(sample.audio_s3_key)
                if not audio_bytes:
                    continue

                ext = ".mp3"
                if sample.audio_s3_key:
                    key_ext = os.path.splitext(sample.audio_s3_key)[1].lower()
                    if key_ext in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
                        ext = key_ext
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
                os.close(tmp_fd)
                with open(tmp_path, "wb") as f:
                    f.write(audio_bytes)

                metrics = qualitative_voice_service.calculate_all_metrics(tmp_path)

                if stt_available and sample.text:
                    selected_stt_provider = ModelProvider(stt_provider_str)
                    selected_language = None
                    if selected_stt_provider == ModelProvider.SARVAM:
                        # Sarvam saarika models accept language_code; saaras models do not.
                        if "saarika" in (stt_model or "").lower():
                            selected_language = "hi-IN"
                    asr_transcript = transcription_service.transcribe_text_only(
                        audio_file_path=tmp_path,
                        stt_provider=selected_stt_provider,
                        stt_model=stt_model,
                        organization_id=comp.organization_id,
                        db=db,
                        language=selected_language,
                    )
                    if asr_transcript:
                        score_bundle = _compute_wer_cer(sample.text, asr_transcript)
                        metrics["WER Raw"] = score_bundle.get("raw_wer")
                        metrics["CER Raw"] = score_bundle.get("raw_cer")
                        metrics["WER Normalized"] = score_bundle.get("normalized_wer")
                        metrics["CER Normalized"] = score_bundle.get("normalized_cer")
                        metrics["WER"] = (
                            score_bundle.get("normalized_wer")
                            if score_bundle.get("normalized_wer") is not None
                            else score_bundle.get("raw_wer")
                        )
                        metrics["CER"] = (
                            score_bundle.get("normalized_cer")
                            if score_bundle.get("normalized_cer") is not None
                            else score_bundle.get("raw_cer")
                        )
                        metrics["ASR Transcript"] = asr_transcript
                    else:
                        metrics["WER"] = None
                        metrics["CER"] = None
                        metrics["WER Raw"] = None
                        metrics["CER Raw"] = None
                        metrics["WER Normalized"] = None
                        metrics["CER Normalized"] = None
                        metrics["ASR Transcript"] = None

                sample.evaluation_metrics = _sanitize_metrics(metrics)
                db.commit()
                evaluated += 1

                logger.info(f"[TTS Eval] Sample {sample.id} metrics: {metrics}")

            except Exception as e:
                logger.warning("[TTS Eval] Sample {} eval failed: {}", sample.id, e)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        from app.api.v1.routes.voice_playground import _recompute_summary

        _recompute_summary(comp, db)

        comp.status = TTSComparisonStatus.COMPLETED.value
        db.commit()

        logger.info(
            f"[TTS Eval] Comparison {comparison_id} complete – {evaluated}/{len(samples)} evaluated"
        )
        return {"evaluated": evaluated}

    except Exception as exc:
        logger.error("[TTS Eval] Task failed: {}", exc, exc_info=True)
        try:
            comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
            if comp:
                comp.status = TTSComparisonStatus.FAILED.value
                comp.error_message = f"Evaluation failed: {str(exc)[:400]}"
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
