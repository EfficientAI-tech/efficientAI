"""Qualitative Voice Metrics Service.

This service calculates advanced qualitative metrics for Voice AI evaluation:
- MOS (Mean Opinion Score): Human-likeness & Audio Fidelity (1.0-5.0)
- Emotional Match Accuracy: Categorical emotion + Valence/Arousal
- Speaker Consistency: Voice identity stability throughout the call
- Prosody Score: Expressiveness/Drama (Monotone vs Storyteller)

These metrics go beyond traditional latency/speed measurements to evaluate
the "human" qualities of Voice AI.
"""

import os
import tempfile
from typing import Dict, Any, Optional, List, Set, Tuple
from pathlib import Path
import numpy as np
from loguru import logger

# Library availability flags
SPEECHMOS_AVAILABLE = False
TRANSFORMERS_AVAILABLE = False
SPEECHBRAIN_AVAILABLE = False
TORCH_AVAILABLE = False
LIBROSA_AVAILABLE = False
PARSELMOUTH_AVAILABLE = False

# Try importing required libraries
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    logger.warning("torch not installed. Qualitative voice metrics will not be available.")

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    logger.warning("librosa not installed. Audio loading may be limited.")

try:
    import parselmouth
    from parselmouth.praat import call
    PARSELMOUTH_AVAILABLE = True
except ImportError:
    logger.warning("praat-parselmouth not installed. Prosody metrics will not be available.")

try:
    from transformers import pipeline, AutoProcessor, AutoModelForAudioClassification
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    logger.warning("transformers not installed. Emotion metrics will not be available.")

# SpeechBrain is optional - disabled by default due to torchaudio version conflicts
# To enable Speaker Consistency metric: pip install speechbrain
SPEECHBRAIN_AVAILABLE = False
try:
    from speechbrain.inference.speaker import EncoderClassifier
    SPEECHBRAIN_AVAILABLE = True
    logger.info("speechbrain loaded successfully. Speaker consistency metric available.")
except ImportError:
    pass  # Expected - speechbrain is optional
except Exception as e:
    logger.debug(f"speechbrain not available: {e}")

# Try SpeechMOS - note: may need to be installed separately
try:
    # SpeechMOS uses torch and provides UTMOS model for MOS prediction
    # If not available, we'll use a fallback approach
    SPEECHMOS_AVAILABLE = TORCH_AVAILABLE
except ImportError:
    logger.warning("SpeechMOS dependencies not fully available.")


# Qualitative metrics names
QUALITATIVE_AUDIO_METRICS: Set[str] = {
    "MOS Score",           # Mean Opinion Score (1.0-5.0)
    "Emotion Category",     # Categorical emotion (angry, happy, sad, neutral, etc.)
    "Emotion Confidence",   # Confidence of emotion prediction
    "Valence",             # Emotional positivity (-1.0 to 1.0)
    "Arousal",             # Emotional intensity (0.0 to 1.0)
    "Speaker Consistency",  # Same voice throughout (0.0-1.0)
    "Prosody Score",       # Expressiveness (0.0-1.0)
}


def is_qualitative_audio_metric(metric_name: str) -> bool:
    """Check if a metric is a qualitative audio metric."""
    return metric_name in QUALITATIVE_AUDIO_METRICS


class QualitativeVoiceMetricsService:
    """Service for calculating qualitative voice metrics."""
    
    def __init__(self):
        """Initialize the service with lazy-loaded models."""
        self._emotion_classifier = None
        self._valence_arousal_model = None
        self._valence_arousal_processor = None
        self._speaker_encoder = None
        self._mos_predictor = None
        self._device = "cuda" if TORCH_AVAILABLE and torch.cuda.is_available() else "cpu"
        logger.info(f"[QualitativeVoice] Initialized with device: {self._device}")
    
    def _load_audio(self, audio_path: str, target_sr: int = 16000) -> Optional[Tuple[np.ndarray, int]]:
        """
        Load audio file and resample to target sample rate.
        
        Args:
            audio_path: Path to audio file
            target_sr: Target sample rate (default 16kHz for speech models)
            
        Returns:
            Tuple of (audio_array, sample_rate) or None if loading failed
        """
        try:
            if LIBROSA_AVAILABLE:
                audio, sr = librosa.load(audio_path, sr=target_sr, mono=True)
                return audio, sr
            else:
                # Fallback using soundfile if librosa not available
                import soundfile as sf
                audio, sr = sf.read(audio_path)
                if len(audio.shape) > 1:
                    audio = audio.mean(axis=1)  # Convert to mono
                if sr != target_sr:
                    # Simple resampling (not ideal but works)
                    import scipy.signal
                    audio = scipy.signal.resample(audio, int(len(audio) * target_sr / sr))
                return audio, target_sr
        except Exception as e:
            logger.error(f"[QualitativeVoice] Failed to load audio: {e}")
            return None
    
    # =========================================================================
    # MOS (Mean Opinion Score) - Human-Likeness & Audio Fidelity
    # =========================================================================
    
    def _get_mos_predictor(self):
        """Lazy load MOS predictor model (UTMOS-based)."""
        if self._mos_predictor is None and TORCH_AVAILABLE:
            try:
                # Try to use UTMOS model from torch hub
                # UTMOS: UTokyo-SaruLab MOS predictor
                logger.info("[QualitativeVoice] Loading MOS predictor (UTMOS)...")
                self._mos_predictor = torch.hub.load(
                    "tarepan/SpeechMOS:v1.2.0", 
                    "utmos22_strong",
                    trust_repo=True
                )
                self._mos_predictor.eval()
                if self._device == "cuda":
                    self._mos_predictor = self._mos_predictor.cuda()
                logger.info("[QualitativeVoice] MOS predictor loaded successfully")
            except Exception as e:
                logger.warning(f"[QualitativeVoice] Could not load UTMOS model: {e}")
                # Fallback: We'll estimate MOS from SNR and other acoustic features
                self._mos_predictor = "fallback"
        return self._mos_predictor
    
    def calculate_mos(self, audio_path: str) -> Optional[float]:
        """
        Calculate Mean Opinion Score (1.0-5.0).
        
        MOS predicts human perception of audio quality:
        - 1.0-2.0: Poor quality (robotic, tin can, bad reception)
        - 3.0: Standard telephone quality
        - 4.0-5.0: Studio/high fidelity quality
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            MOS score (1.0-5.0) or None if calculation failed
        """
        try:
            predictor = self._get_mos_predictor()
            
            if predictor == "fallback":
                # Fallback: Estimate MOS from acoustic features
                return self._estimate_mos_from_acoustics(audio_path)
            
            if predictor is None:
                logger.warning("[QualitativeVoice] MOS predictor not available")
                return None
            
            # Load audio at 16kHz (model requirement)
            audio_data = self._load_audio(audio_path, target_sr=16000)
            if audio_data is None:
                return None
            
            audio, sr = audio_data
            
            # Convert to torch tensor
            audio_tensor = torch.from_numpy(audio).float().unsqueeze(0)
            if self._device == "cuda":
                audio_tensor = audio_tensor.cuda()
            
            # Predict MOS
            with torch.no_grad():
                mos = predictor(audio_tensor, sr)
                mos_value = float(mos.item())
            
            # Clamp to valid range
            mos_value = max(1.0, min(5.0, mos_value))
            logger.info(f"[QualitativeVoice] MOS Score: {mos_value:.2f}")
            return round(mos_value, 2)
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] MOS calculation failed: {e}")
            return self._estimate_mos_from_acoustics(audio_path)
    
    def _estimate_mos_from_acoustics(self, audio_path: str) -> Optional[float]:
        """Fallback MOS estimation using acoustic features."""
        try:
            if not PARSELMOUTH_AVAILABLE:
                return None
            
            sound = parselmouth.Sound(audio_path)
            
            # Get HNR (Harmonics-to-Noise Ratio) - higher = cleaner voice
            harmonicity = sound.to_harmonicity()
            hnr_values = harmonicity.values[harmonicity.values != -200]
            mean_hnr = np.mean(hnr_values) if len(hnr_values) > 0 else 10
            
            # Estimate MOS based on HNR
            # HNR < 10 dB: Poor (MOS ~2)
            # HNR 10-20 dB: Medium (MOS ~3)
            # HNR > 20 dB: Good (MOS ~4-5)
            if mean_hnr < 10:
                mos = 1.5 + (mean_hnr / 10) * 1.0
            elif mean_hnr < 20:
                mos = 2.5 + ((mean_hnr - 10) / 10) * 1.5
            else:
                mos = 4.0 + min(1.0, (mean_hnr - 20) / 20)
            
            mos = max(1.0, min(5.0, mos))
            logger.info(f"[QualitativeVoice] Estimated MOS (from HNR): {mos:.2f}")
            return round(mos, 2)
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] Fallback MOS estimation failed: {e}")
            return None
    
    # =========================================================================
    # Emotional Match Accuracy - Categorical + Valence/Arousal
    # =========================================================================
    
    def _get_emotion_classifier(self):
        """Lazy load emotion classification model."""
        if self._emotion_classifier is None and TRANSFORMERS_AVAILABLE:
            try:
                logger.info("[QualitativeVoice] Loading emotion classifier (wav2vec2-ser)...")
                self._emotion_classifier = pipeline(
                    "audio-classification",
                    model="ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
                    device=0 if self._device == "cuda" else -1
                )
                logger.info("[QualitativeVoice] Emotion classifier loaded successfully")
            except Exception as e:
                logger.error(f"[QualitativeVoice] Failed to load emotion classifier: {e}")
        return self._emotion_classifier
    
    def _get_valence_arousal_model(self):
        """Lazy load valence/arousal model."""
        if self._valence_arousal_model is None and TRANSFORMERS_AVAILABLE:
            try:
                logger.info("[QualitativeVoice] Loading valence/arousal model...")
                model_name = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
                self._valence_arousal_processor = AutoProcessor.from_pretrained(model_name)
                self._valence_arousal_model = AutoModelForAudioClassification.from_pretrained(model_name)
                if self._device == "cuda":
                    self._valence_arousal_model = self._valence_arousal_model.cuda()
                self._valence_arousal_model.eval()
                logger.info("[QualitativeVoice] Valence/arousal model loaded successfully")
            except Exception as e:
                logger.error(f"[QualitativeVoice] Failed to load valence/arousal model: {e}")
        return self._valence_arousal_model
    
    def calculate_emotion_category(self, audio_path: str) -> Tuple[Optional[str], Optional[float]]:
        """
        Classify the dominant emotion in the audio.
        
        Like the "Sorting Hat" - listens and declares one emotion:
        angry, happy, sad, neutral, fearful, disgusted, surprised
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Tuple of (emotion_label, confidence) or (None, None) if failed
        """
        try:
            classifier = self._get_emotion_classifier()
            if classifier is None:
                return None, None
            
            # Run classification
            results = classifier(audio_path)
            
            if results and len(results) > 0:
                top_result = results[0]
                emotion = top_result['label']
                confidence = top_result['score']
                logger.info(f"[QualitativeVoice] Emotion: {emotion} (confidence: {confidence:.2f})")
                return emotion, round(confidence, 3)
            
            return None, None
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] Emotion classification failed: {e}")
            return None, None
    
    def calculate_valence_arousal(self, audio_path: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate Valence and Arousal scores.
        
        Valence (Left/Right): How positive/negative the emotion is (-1.0 to 1.0)
            -1.0 = Very negative (sad, angry)
            +1.0 = Very positive (happy, excited)
            
        Arousal (Up/Down): How intense/activated the emotion is (0.0 to 1.0)
            0.0 = Low energy (sleepy, calm)
            1.0 = High energy (excited, angry)
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Tuple of (valence, arousal) or (None, None) if failed
        """
        try:
            model = self._get_valence_arousal_model()
            if model is None or self._valence_arousal_processor is None:
                return None, None
            
            # Load audio
            audio_data = self._load_audio(audio_path, target_sr=16000)
            if audio_data is None:
                return None, None
            
            audio, sr = audio_data
            
            # Process audio
            inputs = self._valence_arousal_processor(
                audio, 
                sampling_rate=sr, 
                return_tensors="pt"
            )
            if self._device == "cuda":
                inputs = {k: v.cuda() for k, v in inputs.items()}
            
            # Get predictions
            with torch.no_grad():
                outputs = model(**inputs)
                # Model outputs: arousal, dominance, valence
                predictions = outputs.logits.cpu().numpy()[0]
            
            # audeering model outputs: [arousal, dominance, valence]
            arousal = float(predictions[0])
            valence = float(predictions[2])
            
            # Normalize to expected ranges
            # Model outputs are typically in range [0, 1], convert valence to [-1, 1]
            valence = (valence - 0.5) * 2  # Convert from [0,1] to [-1,1]
            arousal = max(0.0, min(1.0, arousal))  # Keep in [0,1]
            
            logger.info(f"[QualitativeVoice] Valence: {valence:.2f}, Arousal: {arousal:.2f}")
            return round(valence, 3), round(arousal, 3)
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] Valence/Arousal calculation failed: {e}")
            return None, None
    
    # =========================================================================
    # Speaker Consistency - Voice Identity Stability
    # =========================================================================
    
    def _get_speaker_encoder(self):
        """Lazy load speaker encoder (ECAPA-TDNN)."""
        if self._speaker_encoder is None and SPEECHBRAIN_AVAILABLE:
            try:
                logger.info("[QualitativeVoice] Loading speaker encoder (ECAPA-TDNN)...")
                self._speaker_encoder = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir="pretrained_models/spkrec-ecapa-voxceleb",
                    run_opts={"device": self._device}
                )
                logger.info("[QualitativeVoice] Speaker encoder loaded successfully")
            except Exception as e:
                logger.error(f"[QualitativeVoice] Failed to load speaker encoder: {e}")
        return self._speaker_encoder
    
    def calculate_speaker_consistency(self, audio_path: str, segment_duration: float = 5.0) -> Optional[float]:
        """
        Calculate speaker consistency score.
        
        Compares voice "fingerprints" from the start and end of the audio
        to detect if the voice changed mid-call (glitch/hallucination).
        
        Score interpretation:
        - > 0.8: Same person throughout (PASS)
        - 0.5-0.8: Possible variation
        - < 0.5: Different person detected (FAIL - possible voice glitch)
        
        Args:
            audio_path: Path to audio file
            segment_duration: Duration of segments to compare (default 5s)
            
        Returns:
            Cosine similarity score (0.0-1.0) or None if failed
        """
        try:
            encoder = self._get_speaker_encoder()
            if encoder is None:
                return None
            
            # Load full audio
            audio_data = self._load_audio(audio_path, target_sr=16000)
            if audio_data is None:
                return None
            
            audio, sr = audio_data
            total_duration = len(audio) / sr
            
            # Need at least 2x segment_duration for comparison
            if total_duration < segment_duration * 2:
                logger.warning(f"[QualitativeVoice] Audio too short for speaker consistency check")
                # If audio is short, assume it's consistent
                return 1.0
            
            # Extract start and end segments
            segment_samples = int(segment_duration * sr)
            start_segment = audio[:segment_samples]
            end_segment = audio[-segment_samples:]
            
            # Convert to torch tensors
            start_tensor = torch.from_numpy(start_segment).float().unsqueeze(0)
            end_tensor = torch.from_numpy(end_segment).float().unsqueeze(0)
            
            # Get embeddings
            with torch.no_grad():
                start_embedding = encoder.encode_batch(start_tensor)
                end_embedding = encoder.encode_batch(end_tensor)
            
            # Calculate cosine similarity
            start_emb = start_embedding.squeeze().cpu().numpy()
            end_emb = end_embedding.squeeze().cpu().numpy()
            
            similarity = np.dot(start_emb, end_emb) / (
                np.linalg.norm(start_emb) * np.linalg.norm(end_emb)
            )
            
            # Convert to 0-1 range (cosine similarity can be negative)
            similarity = (similarity + 1) / 2
            similarity = max(0.0, min(1.0, similarity))
            
            logger.info(f"[QualitativeVoice] Speaker Consistency: {similarity:.3f}")
            return round(similarity, 3)
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] Speaker consistency calculation failed: {e}")
            return None
    
    # =========================================================================
    # Prosody Score - Expressiveness/Drama
    # =========================================================================
    
    def calculate_prosody_score(self, audio_path: str, arousal: Optional[float] = None) -> Optional[float]:
        """
        Calculate prosody/expressiveness score.
        
        Measures "Boring (Monotone)" vs "Dramatic (Storyteller)" by combining:
        - Pitch Variance: Standard deviation of F0 (fundamental frequency)
        - Arousal: Energy/intensity from emotion model
        
        Formula: Expressiveness = (PitchVariance_norm × 0.5) + (Arousal × 0.5)
        
        Args:
            audio_path: Path to audio file
            arousal: Pre-calculated arousal score (if available)
            
        Returns:
            Prosody score (0.0-1.0) or None if failed
        """
        try:
            if not PARSELMOUTH_AVAILABLE:
                logger.warning("[QualitativeVoice] Parselmouth not available for prosody calculation")
                return None
            
            # Load sound
            sound = parselmouth.Sound(audio_path)
            
            # Extract pitch
            pitch = sound.to_pitch()
            pitch_values = pitch.selected_array["frequency"]
            voiced_values = pitch_values[pitch_values > 0]
            
            if len(voiced_values) < 2:
                logger.warning("[QualitativeVoice] Not enough voiced frames for prosody")
                return None
            
            # Calculate pitch variance
            pitch_std = np.std(voiced_values)
            pitch_mean = np.mean(voiced_values)
            
            # Normalize pitch variance (coefficient of variation)
            # Typical CV for speech is 0.1-0.3, higher = more expressive
            cv = pitch_std / pitch_mean if pitch_mean > 0 else 0
            
            # Normalize to 0-1 range
            # CV < 0.1 = monotone, CV > 0.3 = very expressive
            pitch_norm = min(1.0, cv / 0.3)
            
            # Get arousal if not provided
            if arousal is None:
                _, arousal = self.calculate_valence_arousal(audio_path)
            
            if arousal is None:
                # Use only pitch variance if arousal unavailable
                prosody = pitch_norm
            else:
                # Combine pitch variance and arousal
                prosody = (pitch_norm * 0.5) + (arousal * 0.5)
            
            prosody = max(0.0, min(1.0, prosody))
            logger.info(f"[QualitativeVoice] Prosody Score: {prosody:.3f} (pitch_norm={pitch_norm:.3f}, arousal={arousal})")
            return round(prosody, 3)
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] Prosody calculation failed: {e}")
            return None
    
    # =========================================================================
    # Main Entry Point
    # =========================================================================
    
    def calculate_all_metrics(self, audio_path: str) -> Dict[str, Any]:
        """
        Calculate all qualitative voice metrics.
        
        This is the main entry point that runs all metrics and returns
        a comprehensive JSON object.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Dictionary with all metric values
        """
        results: Dict[str, Any] = {}
        
        logger.info(f"[QualitativeVoice] Analyzing audio: {audio_path}")
        
        # MOS Score
        results["MOS Score"] = self.calculate_mos(audio_path)
        
        # Emotion Category
        emotion, confidence = self.calculate_emotion_category(audio_path)
        results["Emotion Category"] = emotion
        results["Emotion Confidence"] = confidence
        
        # Valence & Arousal
        valence, arousal = self.calculate_valence_arousal(audio_path)
        results["Valence"] = valence
        results["Arousal"] = arousal
        
        # Speaker Consistency
        results["Speaker Consistency"] = self.calculate_speaker_consistency(audio_path)
        
        # Prosody Score (uses arousal if available)
        results["Prosody Score"] = self.calculate_prosody_score(audio_path, arousal=arousal)
        
        logger.info(f"[QualitativeVoice] All metrics calculated: {results}")
        return results
    
    def calculate_metrics(
        self,
        audio_source: str,
        metric_names: List[str],
        is_url: bool = True
    ) -> Dict[str, Any]:
        """
        Calculate specific qualitative metrics from audio.
        
        Args:
            audio_source: URL or file path to audio
            metric_names: List of metric names to calculate
            is_url: If True, download from URL first
            
        Returns:
            Dictionary mapping metric names to values
        """
        results: Dict[str, Any] = {}
        temp_file = None
        
        try:
            # Get audio file path
            if is_url:
                from app.services.voice_quality_service import download_audio
                temp_file = download_audio(audio_source)
                if not temp_file:
                    logger.error("[QualitativeVoice] Failed to download audio")
                    return {name: None for name in metric_names}
                audio_path = temp_file
            else:
                audio_path = audio_source
                if not os.path.exists(audio_path):
                    logger.error(f"[QualitativeVoice] Audio file not found: {audio_path}")
                    return {name: None for name in metric_names}
            
            # Calculate requested metrics
            valence, arousal = None, None
            
            for metric_name in metric_names:
                if metric_name not in QUALITATIVE_AUDIO_METRICS:
                    logger.warning(f"[QualitativeVoice] Unknown metric: {metric_name}")
                    results[metric_name] = None
                    continue
                
                if metric_name == "MOS Score":
                    results[metric_name] = self.calculate_mos(audio_path)
                    
                elif metric_name == "Emotion Category":
                    emotion, confidence = self.calculate_emotion_category(audio_path)
                    results["Emotion Category"] = emotion
                    results["Emotion Confidence"] = confidence
                    
                elif metric_name == "Emotion Confidence":
                    if "Emotion Category" not in results:
                        emotion, confidence = self.calculate_emotion_category(audio_path)
                        results["Emotion Category"] = emotion
                        results["Emotion Confidence"] = confidence
                        
                elif metric_name in ("Valence", "Arousal"):
                    if valence is None and arousal is None:
                        valence, arousal = self.calculate_valence_arousal(audio_path)
                    results["Valence"] = valence
                    results["Arousal"] = arousal
                    
                elif metric_name == "Speaker Consistency":
                    results[metric_name] = self.calculate_speaker_consistency(audio_path)
                    
                elif metric_name == "Prosody Score":
                    if arousal is None:
                        _, arousal = self.calculate_valence_arousal(audio_path)
                    results[metric_name] = self.calculate_prosody_score(audio_path, arousal=arousal)
            
            return results
            
        except Exception as e:
            logger.error(f"[QualitativeVoice] Error calculating metrics: {e}")
            return {name: None for name in metric_names}
            
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except Exception:
                    pass


# Singleton instance
qualitative_voice_service = QualitativeVoiceMetricsService()


def calculate_qualitative_metrics(
    audio_source: str,
    metric_names: List[str],
    is_url: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to calculate qualitative voice metrics.
    
    Args:
        audio_source: URL or file path to audio
        metric_names: List of metric names to calculate
        is_url: If True, download from URL first
        
    Returns:
        Dictionary mapping metric names to values
    """
    return qualitative_voice_service.calculate_metrics(audio_source, metric_names, is_url)


def calculate_qualitative_metrics_from_call_data(
    call_data: Optional[Dict[str, Any]],
    provider_platform: Optional[str],
    metric_names: List[str]
) -> Dict[str, Any]:
    """
    Calculate qualitative metrics from provider call data.
    
    Args:
        call_data: Call data from voice provider
        provider_platform: Provider name ('retell', 'vapi')
        metric_names: List of metric names to calculate
        
    Returns:
        Dictionary mapping metric names to values
    """
    from app.services.voice_quality_service import get_recording_url
    
    recording_url = get_recording_url(call_data, provider_platform)
    
    if not recording_url:
        logger.warning(f"[QualitativeVoice] No recording URL found for {provider_platform}")
        return {name: None for name in metric_names}
    
    logger.info(f"[QualitativeVoice] Found recording URL: {recording_url[:80]}...")
    return calculate_qualitative_metrics(recording_url, metric_names, is_url=True)
