"""
Base Voice Provider Interface
All voice providers should inherit from this class
"""
from abc import ABC, abstractmethod 
from typing import Dict, Any, Optional


class BaseVoiceProvider(ABC): 
    """Base class for voice AI provider integrations."""
    
    def __init__(self, api_key: str):
        """
        Initialize the voice provider with an API key.
        
        Args:
            api_key: The API key for the voice provider
        """
        self.api_key = api_key
    
    @abstractmethod
    def create_web_call(self, agent_id: str, **kwargs) -> Dict[str, Any]:
        """
        Create a web call with the voice agent.
        
        Args:
            agent_id: The agent ID from the voice provider
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Dictionary containing call information (access_token, call_id, etc.)
        """
        pass
    
    @abstractmethod
    def create_agent(
        self,
        response_engine: Dict[str, Any],
        voice_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new agent in the voice provider platform.
        
        Args:
            response_engine: Configuration for the response engine (LLM)
            voice_id: Voice ID to use for the agent
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Dictionary containing agent information (agent_id, etc.)
        """
        pass
    
    @abstractmethod
    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Get agent details from the voice provider.
        
        Args:
            agent_id: The agent ID from the voice provider
            
        Returns:
            Dictionary containing agent information
        """
        pass

    @abstractmethod
    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve call metrics and details from the voice provider.
        
        Args:
            call_id: The call ID from the voice provider
            
        Returns:
            Dictionary containing call information (transcript, metrics, etc.)
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test the connection to the voice provider API.
        
        Returns:
            True if connection is successful, raises an exception otherwise.
        """
        pass

