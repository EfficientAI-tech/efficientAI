"""Catalog entries for Bulbul v4, Saaras v4, Scribe v3, and decision LLMs."""

from app.models.database import ModelProvider
from app.services.ai.model_config_service import model_config_service


def test_new_sarvam_stt_and_tts_models_in_catalog():
    stt = model_config_service.get_models_by_type(ModelProvider.SARVAM, "stt")
    tts = model_config_service.get_models_by_type(ModelProvider.SARVAM, "tts")
    assert "saaras:v4" in stt
    assert "bulbul:v4-flash" in tts


def test_bulbul_v4_flash_voices_load_default_persona():
    voices = model_config_service.get_voices_for_model("bulbul:v4-flash")
    assert voices
    ids = {v["id"] for v in voices}
    assert "shubh_enhi_ads" in ids


def test_elevenlabs_scribe_v3_in_catalog():
    stt = model_config_service.get_models_by_type(ModelProvider.ELEVENLABS, "stt")
    assert "scribe_v3" in stt


def test_gemini_decision_1_in_catalog():
    llm = model_config_service.get_models_by_type(ModelProvider.GOOGLE, "llm")
    assert "gemini-decision-1" in llm


def test_microsoft_decision_in_azure_catalog():
    llm = model_config_service.get_models_by_type(ModelProvider.AZURE, "llm")
    assert "Microsoft-Decision-1.1" in llm