"""
Retell Voice Provider Implementation
Handles integration with Retell AI voice agents
"""
from typing import Dict, Any, Optional
from retell import Retell

from app.services.voice_providers.base import BaseVoiceProvider


class RetellVoiceProvider(BaseVoiceProvider):
    """Retell AI voice provider implementation."""
    
    def __init__(self, api_key: str):
        """
        Initialize Retell client.
        
        Args:
            api_key: Retell API key
        """
        super().__init__(api_key)
        self.client = Retell(api_key=api_key)
    
    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        retell_llm_dynamic_variables: Optional[Dict[str, Any]] = None,
        custom_sip_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a web call with Retell agent.
        
        This method uses create_web_call which returns both access_token and call_id.
        The call_id can be used with the frontend SDK's startConversation method.
        
        Args:
            agent_id: Retell agent ID
            metadata: Optional metadata to attach to the call
            retell_llm_dynamic_variables: Optional dynamic variables for the LLM
            custom_sip_headers: Optional custom SIP headers (not supported by Retell SDK)
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing call information including access_token, call_id, etc.
        """
        try:
            # Build parameters dict, only including supported parameters
            call_params = {
                "agent_id": agent_id,
            }
            
            # Only add optional parameters if they are provided and not empty
            if metadata:
                call_params["metadata"] = metadata
            if retell_llm_dynamic_variables:
                call_params["retell_llm_dynamic_variables"] = retell_llm_dynamic_variables
            
            # Note: custom_sip_headers is not supported by Retell SDK's create_web_call
            # If needed in the future, it may be added to the SDK
            
            # Add any additional kwargs that are supported
            call_params.update(kwargs)
            
            # Log the call parameters for debugging (without sensitive data)
            print(f"[Retell] Creating web call with agent_id: {agent_id}")
            
            web_call_response = self.client.call.create_web_call(**call_params)
            
            # Convert the response to a dictionary
            # Handle both Pydantic models and dict responses
            if isinstance(web_call_response, dict):
                return web_call_response
            elif hasattr(web_call_response, "model_dump"):
                # Pydantic v2
                return web_call_response.model_dump()
            elif hasattr(web_call_response, "dict"):
                # Pydantic v1
                return web_call_response.dict()
            else:
                # Fallback to attribute access
                return {
                    "call_type": getattr(web_call_response, "call_type", "web_call"),
                    "access_token": getattr(web_call_response, "access_token", None),
                    "call_id": getattr(web_call_response, "call_id", None),
                    "agent_id": getattr(web_call_response, "agent_id", agent_id),
                    "agent_version": getattr(web_call_response, "agent_version", None),
                    "call_status": getattr(web_call_response, "call_status", "registered"),
                    "agent_name": getattr(web_call_response, "agent_name", None),
                    "metadata": getattr(web_call_response, "metadata", metadata or {}),
                    "retell_llm_dynamic_variables": getattr(
                        web_call_response, "retell_llm_dynamic_variables", retell_llm_dynamic_variables or {}
                    ),
                }
        except Exception as e:
            # Extract more detailed error information
            error_message = str(e)
            
            # Check if it's a Retell API error with more details
            if hasattr(e, 'status_code'):
                error_message = f"Retell API error (status {e.status_code}): {error_message}"
            elif hasattr(e, 'response'):
                try:
                    error_detail = e.response
                    if isinstance(error_detail, dict):
                        error_message = f"Retell API error: {error_detail.get('message', error_message)}"
                except:
                    pass
            
            # Include agent_id in error for debugging
            raise ValueError(
                f"Failed to create Retell web call for agent_id '{agent_id}': {error_message}. "
                f"Please verify: 1) The agent_id exists in Retell, 2) The API key has access to this agent, "
                f"3) The agent is configured for web calls."
            )
    
    def create_agent(
        self,
        response_engine: Dict[str, Any],
        voice_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new Retell agent.
        
        Args:
            response_engine: Configuration for the response engine
                Example: {"llm_id": "llm_234sdertfsdsfsdf", "type": "retell-llm"}
            voice_id: Voice ID to use (e.g., "11labs-Adrian")
            **kwargs: Additional agent configuration parameters
            
        Returns:
            Dictionary containing agent information including agent_id
        """
        try:
            agent_response = self.client.agent.create(
                response_engine=response_engine,
                voice_id=voice_id,
                **kwargs
            )
            
            # Convert the response to a dictionary
            if isinstance(agent_response, dict):
                return agent_response
            elif hasattr(agent_response, "model_dump"):
                return agent_response.model_dump()
            elif hasattr(agent_response, "dict"):
                return agent_response.dict()
            else:
                return {
                    "agent_id": getattr(agent_response, "agent_id", None),
                    "agent_name": getattr(agent_response, "agent_name", None),
                    "voice_id": getattr(agent_response, "voice_id", voice_id),
                    "response_engine": getattr(agent_response, "response_engine", response_engine),
                }
        except Exception as e:
            raise ValueError(f"Failed to create Retell agent: {str(e)}")
    
    def register_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        retell_llm_dynamic_variables: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Register a call with Retell agent (alternative to create_web_call).
        This is the method recommended by the Retell SDK README.
        
        Args:
            agent_id: Retell agent ID
            metadata: Optional metadata to attach to the call
            retell_llm_dynamic_variables: Optional dynamic variables for the LLM
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing call information including call_id, sample_rate, etc.
        """
        try:
            # Build parameters dict
            call_params = {
                "agent_id": agent_id,
            }
            
            if metadata:
                call_params["metadata"] = metadata
            if retell_llm_dynamic_variables:
                call_params["retell_llm_dynamic_variables"] = retell_llm_dynamic_variables
            
            call_params.update(kwargs)
            
            print(f"[Retell] Registering call with agent_id: {agent_id}")
            
            # Try register_call if it exists, otherwise fall back to create_web_call
            if hasattr(self.client.call, 'register'):
                register_response = self.client.call.register(**call_params)
            elif hasattr(self.client.call, 'register_call'):
                register_response = self.client.call.register_call(**call_params)
            else:
                # Fall back to create_web_call
                print("[Retell] register_call not available, using create_web_call")
                return self.create_web_call(agent_id, metadata, retell_llm_dynamic_variables, None, **kwargs)
            
            # Convert response
            if isinstance(register_response, dict):
                return register_response
            elif hasattr(register_response, "model_dump"):
                return register_response.model_dump()
            elif hasattr(register_response, "dict"):
                return register_response.dict()
            else:
                return {
                    "call_id": getattr(register_response, "call_id", None),
                    "sample_rate": getattr(register_response, "sample_rate", 24000),
                }
        except Exception as e:
            raise ValueError(f"Failed to register Retell call: {str(e)}")
    
    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Get Retell agent details.
        
        Args:
            agent_id: Retell agent ID
            
        Returns:
            Dictionary containing agent information
        """
        try:
            agent_response = self.client.agent.retrieve(agent_id=agent_id)
            
            # Convert the response to a dictionary
            if isinstance(agent_response, dict):
                return agent_response
            elif hasattr(agent_response, "model_dump"):
                return agent_response.model_dump()
            elif hasattr(agent_response, "dict"):
                return agent_response.dict()
            else:
                return {
                    "agent_id": getattr(agent_response, "agent_id", agent_id),
                    "agent_name": getattr(agent_response, "agent_name", None),
                    "voice_id": getattr(agent_response, "voice_id", None),
                    "response_engine": getattr(agent_response, "response_engine", None),
                }
        except Exception as e:
            raise ValueError(f"Failed to get Retell agent: {str(e)}")
    
    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve call metrics and details from Retell.
        
        Args:
            call_id: Retell call ID
            
        Returns:
            Dictionary containing call information including metrics, transcript, etc.
        """
        try:
            call_response = self.client.call.retrieve(call_id)
            
            # Convert the response to a dictionary
            if isinstance(call_response, dict):
                return call_response
            elif hasattr(call_response, "model_dump"):
                return call_response.model_dump()
            elif hasattr(call_response, "dict"):
                return call_response.dict()
            else:
                # Fallback to attribute access
                return {
                    "call_id": getattr(call_response, "call_id", call_id),
                    "call_type": getattr(call_response, "call_type", None),
                    "call_status": getattr(call_response, "call_status", None),
                    "transcript": getattr(call_response, "transcript", None),
                    "duration_ms": getattr(call_response, "duration_ms", None),
                    "latency": getattr(call_response, "latency", None),
                    "call_cost": getattr(call_response, "call_cost", None),
                    "call_analysis": getattr(call_response, "call_analysis", None),
                }
        except Exception as e:
            raise ValueError(f"Failed to retrieve Retell call metrics: {str(e)}")

    def test_connection(self) -> bool:
        """
        Test Retell connection by attempting to list agents.
        """
        try:
            self.client.agent.list()
            return True
        except Exception as e:
            raise ValueError(f"Retell connection test failed: {str(e)}")

