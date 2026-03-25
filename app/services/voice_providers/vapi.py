"""
Vapi Voice Provider Implementation
Handles integration with Vapi voice AI agents
"""
from typing import Dict, Any, Optional
import requests
from loguru import logger

from app.services.voice_providers.base import BaseVoiceProvider

# Vapi API configuration
VAPI_API_URL = "https://api.vapi.ai"
VAPI_SAMPLE_RATE = 16000  # Vapi uses 16kHz audio


class VapiVoiceProvider(BaseVoiceProvider):
    """Vapi voice provider implementation."""
    
    def __init__(self, api_key: str, public_key: Optional[str] = None):
        """
        Initialize Vapi client.
        
        Args:
            api_key: Vapi Private API key (used for server-side operations like getting call metrics)
            public_key: Vapi Public API key (used for creating web calls)
        """
        super().__init__(api_key)
        self.public_key = public_key
        self.api_url = VAPI_API_URL
    
    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a web call with Vapi agent.
        
        Makes a POST request to Vapi's /call/web endpoint to create
        a web call session. Returns the call_id and webCallUrl (Daily.co URL)
        needed to connect to the call.
        
        NOTE: Vapi's /call/web endpoint requires the PUBLIC key, not the private key.
        
        Args:
            agent_id: Vapi assistant ID
            metadata: Optional metadata to attach to the call
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing:
                - call_id: Vapi call ID
                - web_call_url: Daily.co room URL for WebRTC connection
                - sample_rate: Audio sample rate (16000 for Vapi)
                - call_type: "web_call"
        """
        try:
            # Log the key configuration for debugging
            logger.info(f"[VapiProvider] create_web_call called - public_key={'set' if self.public_key else 'NOT SET'}, api_key={'set' if self.api_key else 'NOT SET'}")
            
            # Vapi's /call/web endpoint requires the PUBLIC key
            auth_key = self.public_key or self.api_key
            if not self.public_key:
                logger.warning("[VapiProvider] ⚠️ No public_key provided, using api_key. This WILL FAIL for /call/web endpoint!")
            
            if not auth_key:
                raise ValueError("No authentication key available (neither public_key nor api_key)")
            
            url = f"{self.api_url}/call/web"
            headers = {
                'Authorization': f'Bearer {auth_key}',
                'Content-Type': 'application/json'
            }
            
            # Build request payload
            payload = {
                'assistantId': agent_id,
            }
            
            # Add assistant overrides if provided
            if kwargs.get('assistant_overrides'):
                payload['assistantOverrides'] = kwargs['assistant_overrides']
            
            # Add metadata if provided
            if metadata:
                payload['metadata'] = metadata
            
            logger.info(f"[VapiProvider] Creating web call with assistant_id={agent_id}, url={url}")
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            # Log raw response for debugging
            logger.info(f"[VapiProvider] Response status: {response.status_code}")
            
            try:
                data = response.json()
            except Exception as json_err:
                logger.error(f"[VapiProvider] Failed to parse response JSON: {json_err}, raw: {response.text[:500]}")
                raise ValueError(f"Invalid JSON response from Vapi: {response.text[:200]}")
            
            if response.status_code == 201:
                call_id = data.get('id')
                web_call_url = data.get('webCallUrl')
                
                if not call_id:
                    logger.error(f"[VapiProvider] ❌ Response missing 'id' field. Response data: {data}")
                    raise ValueError(f"Vapi API returned success but no call ID. Response: {data}")
                
                if not web_call_url:
                    logger.warning(f"[VapiProvider] ⚠️ Response missing 'webCallUrl' field. Response data: {data}")
                
                logger.info(f"[VapiProvider] ✅ Web call created: call_id={call_id}, web_call_url={'set' if web_call_url else 'NOT SET'}")
                
                return {
                    "call_id": call_id,
                    "web_call_url": web_call_url,
                    "sample_rate": VAPI_SAMPLE_RATE,
                    "call_type": "web_call",
                    "agent_id": agent_id,
                    "metadata": metadata or {},
                    "raw_response": data
                }
            else:
                error_msg = data.get('message', f'Unknown error (status {response.status_code})')
                logger.error(f"[VapiProvider] ❌ Failed to create web call: {error_msg}, full response: {data}")
                raise ValueError(f"Vapi API error: {error_msg}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"[VapiProvider] Request error: {e}")
            raise ValueError(f"Failed to create Vapi web call: {str(e)}")
        except Exception as e:
            logger.error(f"[VapiProvider] Unexpected error: {e}")
            raise ValueError(f"Failed to create Vapi web call: {str(e)}")

    def create_agent(
        self,
        name: str,
        model: Dict[str, Any],
        voice: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new Vapi agent.
        
        Args:
            name: Agent name
            model: Model configuration
            voice: Voice configuration
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing agent information
        """
        try:
            agent_params = {
                "name": name,
                "model": model,
                "voice": voice,
            }
            agent_params.update(kwargs)
            
            # agent_response = self.client.agents.create(**agent_params)
            
            # Placeholder until exact SDK call is confirmed
            return {"message": "Create agent not fully implemented for Vapi", "params": agent_params}
        except Exception as e:
            raise ValueError(f"Failed to create Vapi agent: {str(e)}")

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Get Vapi agent details.
        
        Args:
            agent_id: Vapi agent ID
            
        Returns:
            Dictionary containing agent information
        """
        try:
            # agent_response = self.client.agents.get(agent_id)
            return {"agent_id": agent_id, "name": "Vapi Agent"}
        except Exception as e:
            raise ValueError(f"Failed to get Vapi agent: {str(e)}")

    def update_agent_prompt(self, agent_id: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Update a Vapi assistant's system prompt via PATCH /assistant/{id}.

        Args:
            agent_id: Vapi assistant ID
            system_prompt: New system prompt text

        Returns:
            Updated assistant data from Vapi
        """
        try:
            url = f"{self.api_url}/assistant/{agent_id}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": {
                    "messages": [{"role": "system", "content": system_prompt}],
                },
            }
            logger.info(f"[VapiProvider] Updating assistant prompt: PATCH {url}")
            response = requests.patch(url, headers=headers, json=payload, timeout=30)

            if not response.ok:
                try:
                    error_body = response.json()
                except Exception:
                    error_body = response.text[:500]
                raise ValueError(
                    f"Vapi API error ({response.status_code}): {error_body}"
                )

            data = response.json()
            logger.info(f"[VapiProvider] Assistant {agent_id} prompt updated")
            return data
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to update Vapi assistant prompt: {str(e)}")

    def _make_json_serializable(self, obj: Any) -> Any:
        """
        Recursively convert NumPy types and other non-JSON-serializable types to native Python types.
        """
        import numpy as np
        
        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return obj

    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve call metrics and details from Vapi.
        
        Args:
            call_id: Vapi call ID
            
        Returns:
            Dictionary containing comprehensive call information including:
            - Basic call info (id, status, timestamps, duration)
            - Cost breakdown (transport, STT, LLM, TTS, Vapi fees)
            - Transcript (plain text and structured messages)
            - Analysis (summary, success evaluation)
            - Performance metrics (latencies, interruptions)
            - Recording URLs (mono, stereo, assistant, customer)
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
            }
            
            url = f"{self.api_url}/call/{call_id}"
            logger.debug(f"[VapiProvider] Fetching call metrics: GET {url}")
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if not response.ok:
                try:
                    error_body = response.json()
                except Exception:
                    error_body = response.text[:500]
                logger.error(
                    f"[VapiProvider] GET /call/{call_id} returned {response.status_code}: {error_body}"
                )
                response.raise_for_status()
            
            data = response.json()
            
            logger.info(
                f"[VapiProvider] Retrieved call {call_id}, status: {data.get('status')}, "
                f"ended_reason: {data.get('endedReason')}"
            )
            logger.debug(f"[VapiProvider] Raw call data keys: {list(data.keys())}")

            # Store provider payload as-is and only add generated metadata.
            result = dict(data)
            generated = result.get("generated")
            if not isinstance(generated, dict):
                generated = {}
            generated.update(
                {
                    "provider": "vapi",
                    "schema_mode": "raw_provider_payload",
                    "generated_by": "efficientai",
                }
            )
            result["generated"] = generated

            # Ensure all values are JSON serializable (convert NumPy types, etc.)
            return self._make_json_serializable(result)
        except Exception as e:
            logger.error(f"[VapiProvider] Error getting call metrics: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve Vapi call metrics: {str(e)}")

    def test_connection(self) -> bool:
        """
        Test Vapi connection by attempting to list assistants via HTTP API.
        """
        try:
            url = f"{self.api_url}/assistant"
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                raise ValueError("Invalid API key")
            else:
                data = response.json()
                raise ValueError(f"API error: {data.get('message', 'Unknown error')}")
                
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Vapi connection test failed: {str(e)}")
        except Exception as e:
            raise ValueError(f"Vapi connection test failed: {str(e)}")
