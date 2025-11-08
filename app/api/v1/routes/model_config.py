"""Model configuration API routes."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Any
from app.dependencies import get_api_key
from app.models.database import ModelProvider
from app.services.model_config_service import model_config_service

router = APIRouter(prefix="/model-config", tags=["Model Config"])


@router.get("/models")
async def get_all_models(
    api_key: str = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Get all model configurations.
    
    Returns:
        Dictionary of all model configurations
    """
    try:
        return model_config_service.get_all_models()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading model config: {str(e)}")


@router.get("/models/{model_name}")
async def get_model_config(
    model_name: str,
    api_key: str = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Get configuration for a specific model.
    
    Args:
        model_name: Name of the model
        
    Returns:
        Model configuration
    """
    config = model_config_service.get_model_config(model_name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    return config


@router.get("/providers/{provider}/models")
async def get_models_by_provider(
    provider: str,
    api_key: str = Depends(get_api_key)
) -> List[str]:
    """
    Get all model names for a specific provider.
    
    Args:
        provider: Provider name (openai, anthropic, google, azure, aws)
        
    Returns:
        List of model names
    """
    try:
        provider_enum = ModelProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")
    
    return model_config_service.get_models_by_provider(provider_enum)


@router.get("/providers/{provider}/options")
async def get_model_options(
    provider: str,
    api_key: str = Depends(get_api_key)
) -> Dict[str, List[str]]:
    """
    Get model options organized by type (stt, llm, tts) for a provider.
    
    Args:
        provider: Provider name (openai, anthropic, google, azure, aws)
        
    Returns:
        Dict with keys 'stt', 'llm', 'tts' and values as lists of model names
    """
    try:
        provider_enum = ModelProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")
    
    return model_config_service.get_model_options_by_provider(provider_enum)


@router.get("/providers/{provider}/types/{model_type}/models")
async def get_models_by_type(
    provider: str,
    model_type: str,
    api_key: str = Depends(get_api_key)
) -> List[str]:
    """
    Get models by provider and type.
    
    Args:
        provider: Provider name (openai, anthropic, google, azure, aws)
        model_type: One of 'stt', 'llm', 'tts'
        
    Returns:
        List of model names
    """
    if model_type not in ['stt', 'llm', 'tts']:
        raise HTTPException(status_code=400, detail=f"Invalid model_type: {model_type}. Must be one of: stt, llm, tts")
    
    try:
        provider_enum = ModelProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")
    
    return model_config_service.get_models_by_type(provider_enum, model_type)

