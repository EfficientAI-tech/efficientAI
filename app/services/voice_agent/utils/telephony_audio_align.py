"""Align and merge dual-track telephony pipeline recordings for natural mono playback."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

import numpy as np
from loguru import logger
from scipy.signal import correlate

from app.config import settings


class TelephonyMergeStrategy(str, Enum):
    USER_ONLY = "user_only"
    ALIGNED_MIX = "aligned_mix"


@dataclass
class TelephonyTrackAnalysis:
    strategy: TelephonyMergeStrategy
    bot_delay_samples: int
    correlation_peak: float
    correlation_lag_samples: int
    leak_peak: float
    user_sample_rate: int
    user_duration_samples: int
    bot_duration_samples: int
    reason: str


def read_wav_mono(path: str) -> Tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        if sample_width != 2:
            raise ValueError(f"Unsupported sample width {sample_width} in {path}")
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16)
    if num_channels > 1:
        samples = samples.reshape(-1, num_channels).mean(axis=1).astype(np.int16)
    return samples, sample_rate


def _rms_envelope(samples: np.ndarray, frame_size: int) -> np.ndarray:
    if len(samples) == 0:
        return np.zeros(0, dtype=np.float32)
    pad = (-len(samples)) % frame_size
    if pad:
        samples = np.pad(samples, (0, pad))
    frames = samples.reshape(-1, frame_size).astype(np.float32)
    return np.sqrt(np.mean(frames * frames, axis=1))


def _bot_speech_leak_correlation(
    user: np.ndarray,
    bot: np.ndarray,
    *,
    sample_rate: int,
) -> float:
    """Correlation on frames where the bot track is active (echo / bleed detection)."""
    frame = max(1, sample_rate // 50)
    user_env = _rms_envelope(user, frame)
    bot_env = _rms_envelope(bot, frame)
    min_len = min(len(user_env), len(bot_env))
    if min_len < 4:
        return 0.0
    user_env = user_env[:min_len]
    bot_env = bot_env[:min_len]
    active = bot_env > max(float(bot_env.max()) * 0.2, 1.0)
    if not np.any(active):
        return 0.0
    active_user = user_env[active] - user_env[active].mean()
    active_bot = bot_env[active] - bot_env[active].mean()
    user_norm = np.linalg.norm(active_user)
    bot_norm = np.linalg.norm(active_bot)
    if user_norm < 1e-6 or bot_norm < 1e-6:
        return 0.0
    return float(np.dot(active_user, active_bot) / (user_norm * bot_norm))


def estimate_bot_lag_samples(
    user: np.ndarray,
    bot: np.ndarray,
    *,
    sample_rate: int,
    max_lag_ms: int = 4000,
) -> Tuple[int, float]:
    """Return (lag_samples, normalized_peak) of the envelope cross-correlation peak.

    DIAGNOSTIC ONLY -- do not use this lag to align the tracks. The user and bot
    envelopes are anti-correlated in a turn-taking conversation, so the argmax is
    the lag that best superimposes bot speech onto user speech, i.e. it maximises
    overlap. It is meaningful only when both tracks carry the same signal (echo).
    """
    if len(user) < sample_rate // 10 or len(bot) < sample_rate // 20:
        return 0, 0.0

    frame = max(1, sample_rate // 50)
    user_env = _rms_envelope(user, frame)
    bot_env = _rms_envelope(bot, frame)
    if len(user_env) < 4 or len(bot_env) < 4:
        return 0, 0.0

    user_env = user_env - user_env.mean()
    bot_env = bot_env - bot_env.mean()
    user_norm = np.linalg.norm(user_env)
    bot_norm = np.linalg.norm(bot_env)
    if user_norm < 1e-6 or bot_norm < 1e-6:
        return 0, 0.0

    max_lag_frames = max(1, int(max_lag_ms / (1000 * frame / sample_rate)))
    corr = correlate(user_env, bot_env, mode="full", method="fft")
    center = len(bot_env) - 1
    lo = max(0, center - max_lag_frames)
    hi = min(len(corr), center + max_lag_frames + 1)
    window = corr[lo:hi]
    if len(window) == 0:
        return 0, 0.0
    peak_idx = int(np.argmax(window))
    lag_frames = (lo + peak_idx) - center
    peak = float(window[peak_idx] / (user_norm * bot_norm))
    return lag_frames * frame, peak


def analyze_dual_tracks(
    user_samples: np.ndarray,
    bot_samples: np.ndarray,
    *,
    sample_rate: int,
    call_direction: Optional[str] = None,
) -> TelephonyTrackAnalysis:
    corr_lag, peak = estimate_bot_lag_samples(user_samples, bot_samples, sample_rate=sample_rate)

    leak_peak = _bot_speech_leak_correlation(
        user_samples,
        bot_samples,
        sample_rate=sample_rate,
    )

    if len(bot_samples) < sample_rate // 20:
        return TelephonyTrackAnalysis(
            strategy=TelephonyMergeStrategy.USER_ONLY,
            bot_delay_samples=0,
            correlation_peak=peak,
            correlation_lag_samples=corr_lag,
            leak_peak=leak_peak,
            user_sample_rate=sample_rate,
            user_duration_samples=len(user_samples),
            bot_duration_samples=len(bot_samples),
            reason="bot_track_too_short",
        )

    # Both recorders now timestamp against the same wall clock at true playout
    # time (the bot recorder sits downstream of the transport output and anchors
    # each utterance to BotStartedSpeaking), so the tracks are already aligned.
    # The only legitimate shift left is a measured residual carrier latency;
    # corr_lag is deliberately NOT applied -- see estimate_bot_lag_samples.
    residual_delay_ms = int(getattr(settings, "TELEPHONY_BOT_PLAYBACK_DELAY_MS", 0))
    bot_delay = max(0, int(sample_rate * residual_delay_ms / 1000))

    return TelephonyTrackAnalysis(
        strategy=TelephonyMergeStrategy.ALIGNED_MIX,
        bot_delay_samples=bot_delay,
        correlation_peak=peak,
        correlation_lag_samples=corr_lag,
        leak_peak=leak_peak,
        user_sample_rate=sample_rate,
        user_duration_samples=len(user_samples),
        bot_duration_samples=len(bot_samples),
        reason="aligned_mix",
    )


def _shift_pad(samples: np.ndarray, delay_samples: int) -> np.ndarray:
    if delay_samples <= 0:
        return samples
    return np.pad(samples, (delay_samples, 0), mode="constant")


def mix_aligned_mono(
    user_samples: np.ndarray,
    bot_samples: np.ndarray,
    *,
    bot_delay_samples: int,
) -> np.ndarray:
    bot_shifted = _shift_pad(bot_samples, bot_delay_samples)
    max_len = max(len(user_samples), len(bot_shifted))
    user_padded = np.pad(user_samples, (0, max_len - len(user_samples)), mode="constant")
    bot_padded = np.pad(bot_shifted, (0, max_len - len(bot_shifted)), mode="constant")
    mixed = user_padded.astype(np.int32) + bot_padded.astype(np.int32)
    return np.clip(mixed, -32768, 32767).astype(np.int16)


def write_wav_mono(path: str, samples: np.ndarray, sample_rate: int) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.astype(np.int16).tobytes())


def merge_telephony_tracks_to_mono(
    user_audio_path: str,
    bot_audio_path: str,
    *,
    output_path: str,
    call_direction: Optional[str] = None,
) -> Tuple[TelephonyTrackAnalysis, float]:
    user, user_rate = read_wav_mono(user_audio_path)
    bot, bot_rate = read_wav_mono(bot_audio_path)
    if user_rate != bot_rate and len(bot) > 0:
        logger.warning(
            "Telephony merge sample-rate mismatch user={} bot={}; using user rate {}",
            user_rate,
            bot_rate,
            user_rate,
        )
        ratio = user_rate / bot_rate
        new_len = int(len(bot) * ratio)
        bot = np.interp(
            np.linspace(0, len(bot) - 1, new_len),
            np.arange(len(bot)),
            bot.astype(np.float32),
        ).astype(np.int16)

    analysis = analyze_dual_tracks(user, bot, sample_rate=user_rate, call_direction=call_direction)

    logger.info(
        "Telephony merge analysis strategy={} reason={} corr_peak={:.3f} corr_lag_samples={} "
        "leak_peak={:.3f} bot_delay_samples={} user_samples={} bot_samples={}",
        analysis.strategy.value,
        analysis.reason,
        analysis.correlation_peak,
        analysis.correlation_lag_samples,
        analysis.leak_peak,
        analysis.bot_delay_samples,
        analysis.user_duration_samples,
        analysis.bot_duration_samples,
    )

    leak_threshold = float(getattr(settings, "TELEPHONY_MERGE_CORRELATION_DOUBLE_COUNT", 0.35))
    if analysis.leak_peak >= leak_threshold:
        logger.warning(
            "Telephony merge: inbound user track appears to already contain bot speech "
            "(leak_peak={:.3f}). The carrier is likely mixing the agent leg back into the "
            "inbound stream; summing the bot track will duplicate it.",
            analysis.leak_peak,
        )

    if analysis.strategy == TelephonyMergeStrategy.USER_ONLY:
        merged = user
    else:
        merged = mix_aligned_mono(
            user,
            bot,
            bot_delay_samples=analysis.bot_delay_samples,
        )

    write_wav_mono(output_path, merged, user_rate)
    duration = len(merged) / float(user_rate) if user_rate else 0.0
    return analysis, duration
