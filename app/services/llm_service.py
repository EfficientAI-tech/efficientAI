"""
LLM service for generating text responses using various LLM providers.
"""

import time
from typing import Optional, Dict, Any, List
from uuid import UUID

from app.models.database import ModelProvider, AIProvider
from sqlalchemy.orm import Session


class LLMService:
    """Service for generating text responses using various LLM providers."""

    def __init__(self):
        """Initialize LLM service."""
        pass

    def _get_ai_provider(self, provider: ModelProvider, db: Session, organization_id: UUID) -> Optional[AIProvider]:
        """Get AI provider configuration from database."""
        ai_provider = db.query(AIProvider).filter(
            AIProvider.provider == provider,
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True
        ).first()
        return ai_provider

    def _generate_with_openai(
        self,
        messages: List[Dict[str, str]],
        model: str,
        api_key: str,
        temperature: Optional[float] = 0.7,
        max_tokens: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generate response using OpenAI API."""
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=api_key)
            
            # Prepare request parameters
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            
            if max_tokens:
                request_params["max_tokens"] = max_tokens
            
            # Add any additional config
            if config:
                request_params.update(config)
            
            response = client.chat.completions.create(**request_params)
            
            return {
                "text": response.choices[0].message.content,
                "model": model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                "raw_response": response
            }
        except ImportError:
            raise RuntimeError("OpenAI library not installed. Install with: pip install openai")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"OpenAI LLM generation failed: {str(e)}\nDetails: {error_details}")

    def _generate_with_anthropic(
        self,
        messages: List[Dict[str, str]],
        model: str,
        api_key: str,
        temperature: Optional[float] = 0.7,
        max_tokens: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generate response using Anthropic Claude API."""
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=api_key)
            
            # Convert messages format (Anthropic uses different format)
            system_message = None
            conversation_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    conversation_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            # Prepare request parameters
            request_params = {
                "model": model,
                "messages": conversation_messages,
                "temperature": temperature,
            }
            
            if system_message:
                request_params["system"] = system_message
            
            if max_tokens:
                request_params["max_tokens"] = max_tokens
            
            # Add any additional config
            if config:
                request_params.update(config)
            
            response = client.messages.create(**request_params)
            
            return {
                "text": response.content[0].text if response.content else "",
                "model": model,
                "usage": {
                    "prompt_tokens": response.usage.input_tokens if response.usage else 0,
                    "completion_tokens": response.usage.output_tokens if response.usage else 0,
                    "total_tokens": (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0,
                },
                "raw_response": response
            }
        except ImportError:
            raise RuntimeError("Anthropic library not installed. Install with: pip install anthropic")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"Anthropic LLM generation failed: {str(e)}\nDetails: {error_details}")

    def _generate_with_google(
        self,
        messages: List[Dict[str, str]],
        model: str,
        api_key: str,
        temperature: Optional[float] = 0.7,
        max_tokens: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generate response using Google Gemini API."""
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=api_key)
            
            # Convert messages to Gemini format
            # Gemini uses a different message format
            system_instruction = None
            conversation_history = []
            
            for msg in messages:
                if msg["role"] == "system":
                    system_instruction = msg["content"]
                else:
                    conversation_history.append({
                        "role": msg["role"],
                        "parts": [msg["content"]]
                    })
            
            # Create model instance
            model_instance = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_instruction
            )
            
            # Generate response
            response = model_instance.generate_content(
                conversation_history[-1]["parts"][0] if conversation_history else "",
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    **(config or {})
                }
            )
            
            return {
                "text": response.text,
                "model": model,
                "usage": {
                    "prompt_tokens": response.usage_metadata.prompt_token_count if hasattr(response, 'usage_metadata') else 0,
                    "completion_tokens": response.usage_metadata.candidates_token_count if hasattr(response, 'usage_metadata') else 0,
                    "total_tokens": response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0,
                },
                "raw_response": response
            }
        except ImportError:
            raise RuntimeError("Google Generative AI library not installed. Install with: pip install google-generativeai")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"Google LLM generation failed: {str(e)}\nDetails: {error_details}")

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        llm_provider: ModelProvider,
        llm_model: str,
        organization_id: UUID,
        db: Session,
        temperature: Optional[float] = 0.7,
        max_tokens: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a text response using the specified LLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            llm_provider: LLM provider to use
            llm_model: LLM model name
            organization_id: Organization ID
            db: Database session
            temperature: Temperature for generation (0.0-2.0)
            max_tokens: Maximum tokens to generate
            config: Additional provider-specific configuration
            
        Returns:
            Dictionary with generated text and metadata
        """
        start_time = time.time()
        
        # Get provider API key
        ai_provider = self._get_ai_provider(llm_provider, db, organization_id)
        if not ai_provider:
            raise RuntimeError(f"AI provider {llm_provider} not configured for this organization.")
        
        # Decrypt API key
        from app.core.encryption import decrypt_api_key
        try:
            api_key = decrypt_api_key(ai_provider.api_key)
        except Exception as e:
            raise RuntimeError(f"Failed to decrypt API key for provider {llm_provider}: {str(e)}")
        
        # Generate based on provider
        if llm_provider == ModelProvider.OPENAI:
            result = self._generate_with_openai(messages, llm_model, api_key, temperature, max_tokens, config)
        elif llm_provider == ModelProvider.ANTHROPIC:
            result = self._generate_with_anthropic(messages, llm_model, api_key, temperature, max_tokens, config)
        elif llm_provider == ModelProvider.GOOGLE:
            result = self._generate_with_google(messages, llm_model, api_key, temperature, max_tokens, config)
        else:
            raise NotImplementedError(f"LLM provider {llm_provider} not yet implemented")
        
        processing_time = time.time() - start_time
        result["processing_time"] = processing_time
        
        return result


# Singleton instance
llm_service = LLMService()

