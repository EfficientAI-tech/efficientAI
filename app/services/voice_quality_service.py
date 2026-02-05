"""Voice quality metrics service using Praat-Parselmouth.

This service calculates acoustic/voice quality metrics from audio files:
- Pitch Variance: F0 (fundamental frequency) variation
- Jitter: Cycle-to-cycle pitch period variation
- Shimmer: Cycle-to-cycle amplitude variation  
- HNR: Harmonics-to-Noise Ratio

These metrics are industry-standard measures used in voice quality assessment.
"""

import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional, Set, List
import numpy as np
from loguru import logger

try:
    import parselmouth
    from parselmouth.praat import call
    PARSELMOUTH_AVAILABLE = True
except ImportError:
    PARSELMOUTH_AVAILABLE = False
    logger.warning("praat-parselmouth not installed. Voice quality metrics will not be available.")


# Fixed set of audio metrics (identified by name)
# These are industry-standard acoustic measures
AUDIO_METRICS: Set[str] = {
    # Traditional acoustic metrics (Parselmouth)
    "Pitch Variance",
    "Jitter",
    "Shimmer",
    "HNR",
    # Qualitative Voice AI metrics (new)
    "MOS Score",           # Mean Opinion Score (1.0-5.0) - Human-likeness
    "Emotion Category",     # Categorical emotion (angry, happy, etc.)
    "Emotion Confidence",   # Confidence of emotion prediction
    "Valence",             # Emotional positivity (-1.0 to 1.0)
    "Arousal",             # Emotional intensity (0.0 to 1.0)
    "Speaker Consistency",  # Same voice throughout (0.0-1.0)
    "Prosody Score",       # Expressiveness (0.0-1.0)
}


def is_audio_metric(metric_name: str) -> bool:
    """
    Check if a metric should be evaluated from audio (not LLM).
    
    Args:
        metric_name: Name of the metric
        
    Returns:
        True if this metric requires audio analysis
    """
    return metric_name in AUDIO_METRICS


def get_recording_url(call_data: Optional[Dict[str, Any]], provider_platform: Optional[str]) -> Optional[str]:
    """
    Extract recording URL from provider call_data.
    
    Args:
        call_data: Call data from voice provider (Retell/Vapi)
        provider_platform: Provider name ('retell', 'vapi')
        
    Returns:
        Recording URL or None if not available
    """
    if not call_data:
        return None
    
    if provider_platform == "vapi":
        # Vapi stores recording URLs in recording_urls object
        recording_urls = call_data.get("recording_urls", {})
        return (
            recording_urls.get("combined_url") or
            recording_urls.get("stereo_url") or
            call_data.get("recordingUrl")
        )
    elif provider_platform == "retell":
        # Retell stores recording URL directly
        return call_data.get("recording_url")
    else:
        # Try common patterns for unknown providers
        return (
            call_data.get("recording_url") or
            call_data.get("recordingUrl") or
            call_data.get("recording_urls", {}).get("combined_url")
        )


def download_audio(url: str, timeout: float = 60.0) -> Optional[str]:
    """
    Download audio from URL to a temporary file.
    
    Args:
        url: URL of the audio file
        timeout: Download timeout in seconds
        
    Returns:
        Path to temporary file, or None if download failed
    """
    import httpx
    
    try:
        logger.info(f"[VoiceQuality] Downloading audio from URL: {url[:100]}...")
        
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            
            # Determine file extension from content-type or URL
            content_type = response.headers.get("content-type", "")
            if "wav" in content_type or url.endswith(".wav"):
                suffix = ".wav"
            elif "mp3" in content_type or url.endswith(".mp3"):
                suffix = ".mp3"
            elif "ogg" in content_type or url.endswith(".ogg"):
                suffix = ".ogg"
            else:
                suffix = ".wav"  # Default to wav
            
            # Create temporary file
            fd, temp_path = tempfile.mkstemp(suffix=suffix)
            try:
                os.write(fd, response.content)
            finally:
                os.close(fd)
            
            logger.info(f"[VoiceQuality] Downloaded audio to: {temp_path} ({len(response.content)} bytes)")
            return temp_path
            
    except Exception as e:
        logger.error(f"[VoiceQuality] Failed to download audio: {e}")
        return None


def _load_sound(audio_path: str) -> Optional["parselmouth.Sound"]:
    """
    Load audio file as Parselmouth Sound object.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Parselmouth Sound object or None if loading failed
    """
    if not PARSELMOUTH_AVAILABLE:
        logger.error("[VoiceQuality] Parselmouth not available")
        return None
    
    try:
        sound = parselmouth.Sound(audio_path)
        logger.info(f"[VoiceQuality] Loaded audio: duration={sound.duration:.2f}s, sample_rate={sound.sampling_frequency}")
        return sound
    except Exception as e:
        logger.error(f"[VoiceQuality] Failed to load audio: {e}")
        return None


def calculate_pitch_variance(sound: "parselmouth.Sound") -> Optional[float]:
    """
    Calculate pitch (F0) variance.
    
    Pitch variance measures the variation in fundamental frequency,
    indicating prosodic expressiveness. Higher values suggest more
    expressive speech, while very low values may indicate monotone speech.
    
    Args:
        sound: Parselmouth Sound object
        
    Returns:
        Pitch variance in Hz, or None if calculation failed
    """
    try:
        # Extract pitch using default settings (75-600 Hz range, suitable for speech)
        pitch = sound.to_pitch()
        
        # Get pitch values, filtering out unvoiced frames (which have value 0)
        pitch_values = pitch.selected_array["frequency"]
        voiced_values = pitch_values[pitch_values > 0]
        
        if len(voiced_values) < 2:
            logger.warning("[VoiceQuality] Not enough voiced frames for pitch variance")
            return None
        
        variance = float(np.std(voiced_values))
        logger.debug(f"[VoiceQuality] Pitch variance: {variance:.2f} Hz")
        return round(variance, 2)
        
    except Exception as e:
        logger.error(f"[VoiceQuality] Pitch variance calculation failed: {e}")
        return None


def calculate_jitter(sound: "parselmouth.Sound") -> Optional[float]:
    """
    Calculate local jitter (pitch period perturbation).
    
    Jitter measures cycle-to-cycle variation in pitch period,
    indicating vocal stability. Lower values (< 1%) indicate
    stable voice, while higher values may indicate voice disorders.
    
    Args:
        sound: Parselmouth Sound object
        
    Returns:
        Jitter as percentage (0-100), or None if calculation failed
    """
    try:
        # Extract pitch and create point process
        pitch = sound.to_pitch()
        point_process = call(sound, "To PointProcess (periodic, cc)", 75, 600)
        
        # Calculate local jitter
        jitter = call(point_process, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        
        # Convert to percentage
        jitter_percent = jitter * 100
        logger.debug(f"[VoiceQuality] Jitter: {jitter_percent:.4f}%")
        return round(jitter_percent, 4)
        
    except Exception as e:
        logger.error(f"[VoiceQuality] Jitter calculation failed: {e}")
        return None


def calculate_shimmer(sound: "parselmouth.Sound") -> Optional[float]:
    """
    Calculate local shimmer (amplitude perturbation).
    
    Shimmer measures cycle-to-cycle variation in amplitude,
    indicating voice quality. Lower values (< 3%) indicate
    consistent voice, while higher values may indicate breathiness.
    
    Args:
        sound: Parselmouth Sound object
        
    Returns:
        Shimmer as percentage (0-100), or None if calculation failed
    """
    try:
        # Create point process for shimmer calculation
        point_process = call(sound, "To PointProcess (periodic, cc)", 75, 600)
        
        # Calculate local shimmer
        shimmer = call(
            [sound, point_process], 
            "Get shimmer (local)", 
            0, 0, 0.0001, 0.02, 1.3, 1.6
        )
        
        # Convert to percentage
        shimmer_percent = shimmer * 100
        logger.debug(f"[VoiceQuality] Shimmer: {shimmer_percent:.4f}%")
        return round(shimmer_percent, 4)
        
    except Exception as e:
        logger.error(f"[VoiceQuality] Shimmer calculation failed: {e}")
        return None


def calculate_hnr(sound: "parselmouth.Sound") -> Optional[float]:
    """
    Calculate Harmonics-to-Noise Ratio (HNR).
    
    HNR measures the ratio of periodic (harmonic) to aperiodic (noise)
    components in the voice signal. Higher values (> 20 dB) indicate
    cleaner voice with less breathiness or hoarseness.
    
    Args:
        sound: Parselmouth Sound object
        
    Returns:
        HNR in dB, or None if calculation failed
    """
    try:
        # Calculate harmonicity
        harmonicity = sound.to_harmonicity()
        
        # Get HNR values, excluding undefined values (-200 dB)
        hnr_values = harmonicity.values[harmonicity.values != -200]
        
        if len(hnr_values) == 0:
            logger.warning("[VoiceQuality] No valid HNR values found")
            return None
        
        mean_hnr = float(np.mean(hnr_values))
        logger.debug(f"[VoiceQuality] HNR: {mean_hnr:.2f} dB")
        return round(mean_hnr, 2)
        
    except Exception as e:
        logger.error(f"[VoiceQuality] HNR calculation failed: {e}")
        return None


# Traditional Parselmouth metrics
PARSELMOUTH_METRICS: Set[str] = {
    "Pitch Variance",
    "Jitter",
    "Shimmer",
    "HNR",
}

# Qualitative AI metrics
QUALITATIVE_METRICS: Set[str] = {
    "MOS Score",
    "Emotion Category",
    "Emotion Confidence",
    "Valence",
    "Arousal",
    "Speaker Consistency",
    "Prosody Score",
}


def calculate_audio_metrics(
    audio_source: str,
    metric_names: List[str],
    is_url: bool = True
) -> Dict[str, Any]:
    """
    Calculate voice quality metrics from audio.
    
    This is the main entry point for voice quality analysis.
    Handles both traditional Parselmouth metrics and new qualitative AI metrics.
    
    Args:
        audio_source: URL or file path to audio
        metric_names: List of metric names to calculate (from AUDIO_METRICS)
        is_url: If True, audio_source is a URL to download; if False, it's a file path
        
    Returns:
        Dictionary mapping metric names to their values.
        Values are None if calculation failed.
    """
    results: Dict[str, Any] = {}
    
    # Separate metrics into Parselmouth and Qualitative
    parselmouth_metrics = [m for m in metric_names if m in PARSELMOUTH_METRICS]
    qualitative_metrics = [m for m in metric_names if m in QUALITATIVE_METRICS]
    
    # Calculate Parselmouth metrics
    if parselmouth_metrics:
        if not PARSELMOUTH_AVAILABLE:
            logger.error("[VoiceQuality] Parselmouth not installed, returning None for Parselmouth metrics")
            results.update({name: None for name in parselmouth_metrics})
        else:
            parselmouth_results = _calculate_parselmouth_metrics(audio_source, parselmouth_metrics, is_url)
            results.update(parselmouth_results)
    
    # Calculate Qualitative metrics
    if qualitative_metrics:
        try:
            from app.services.qualitative_voice_service import calculate_qualitative_metrics
            qualitative_results = calculate_qualitative_metrics(audio_source, qualitative_metrics, is_url)
            results.update(qualitative_results)
        except ImportError as e:
            logger.warning(f"[VoiceQuality] Qualitative voice service not available: {e}")
            results.update({name: None for name in qualitative_metrics})
        except Exception as e:
            logger.error(f"[VoiceQuality] Error calculating qualitative metrics: {e}")
            results.update({name: None for name in qualitative_metrics})
    
    # Handle any unknown metrics
    unknown_metrics = [m for m in metric_names if m not in AUDIO_METRICS]
    for metric_name in unknown_metrics:
        logger.warning(f"[VoiceQuality] Unknown audio metric: {metric_name}")
        results[metric_name] = None
    
    logger.info(f"[VoiceQuality] Calculated metrics: {results}")
    return results


def _calculate_parselmouth_metrics(
    audio_source: str,
    metric_names: List[str],
    is_url: bool = True
) -> Dict[str, Any]:
    """
    Calculate traditional Parselmouth-based metrics.
    
    Args:
        audio_source: URL or file path to audio
        metric_names: List of Parselmouth metric names to calculate
        is_url: If True, download from URL first
        
    Returns:
        Dictionary mapping metric names to values
    """
    results: Dict[str, Any] = {}
    temp_file = None
    
    try:
        # Get audio file path
        if is_url:
            temp_file = download_audio(audio_source)
            if not temp_file:
                logger.error("[VoiceQuality] Failed to download audio")
                return {name: None for name in metric_names}
            audio_path = temp_file
        else:
            audio_path = audio_source
            if not os.path.exists(audio_path):
                logger.error(f"[VoiceQuality] Audio file not found: {audio_path}")
                return {name: None for name in metric_names}
        
        # Load sound
        sound = _load_sound(audio_path)
        if sound is None:
            return {name: None for name in metric_names}
        
        # Calculate requested metrics
        for metric_name in metric_names:
            if metric_name == "Pitch Variance":
                results[metric_name] = calculate_pitch_variance(sound)
            elif metric_name == "Jitter":
                results[metric_name] = calculate_jitter(sound)
            elif metric_name == "Shimmer":
                results[metric_name] = calculate_shimmer(sound)
            elif metric_name == "HNR":
                results[metric_name] = calculate_hnr(sound)
        
        return results
        
    except Exception as e:
        logger.error(f"[VoiceQuality] Error calculating Parselmouth metrics: {e}")
        return {name: None for name in metric_names}
        
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
                logger.debug(f"[VoiceQuality] Cleaned up temp file: {temp_file}")
            except Exception as e:
                logger.warning(f"[VoiceQuality] Failed to clean up temp file: {e}")


def calculate_audio_metrics_from_call_data(
    call_data: Optional[Dict[str, Any]],
    provider_platform: Optional[str],
    metric_names: List[str]
) -> Dict[str, Any]:
    """
    Calculate voice quality metrics from provider call data.
    
    Convenience function that extracts the recording URL from call_data
    and calculates the requested metrics.
    
    Args:
        call_data: Call data from voice provider (Retell/Vapi)
        provider_platform: Provider name ('retell', 'vapi')
        metric_names: List of metric names to calculate
        
    Returns:
        Dictionary mapping metric names to their values
    """
    recording_url = get_recording_url(call_data, provider_platform)
    
    if not recording_url:
        logger.warning(f"[VoiceQuality] No recording URL found in call_data for {provider_platform}")
        return {name: None for name in metric_names}
    
    logger.info(f"[VoiceQuality] Found recording URL for {provider_platform}: {recording_url[:80]}...")
    return calculate_audio_metrics(recording_url, metric_names, is_url=True)
