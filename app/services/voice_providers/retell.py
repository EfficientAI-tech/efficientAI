"""
Retell Voice Provider Implementation
Handles integration with Retell AI voice agents
"""
from typing import Dict, Any, Optional, Set
from retell import Retell
from loguru import logger

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
            error_message = str(e)

            # Try to extract the human-readable message from Retell's API error body
            upstream_msg = None
            if hasattr(e, 'body') and isinstance(e.body, dict):
                upstream_msg = e.body.get('message')
            elif hasattr(e, 'response') and isinstance(e.response, dict):
                upstream_msg = e.response.get('message')

            if upstream_msg:
                error_message = upstream_msg
            elif hasattr(e, 'status_code'):
                error_message = f"Retell API error (status {e.status_code}): {error_message}"

            raise ValueError(
                f"Retell: {error_message}"
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

    def list_agents(
        self,
        *,
        page_size: int = 30,
        search: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Retell agents and normalize to external-agents response shape."""
        try:
            del cursor  # Retell SDK currently handles pagination internally.
            response = self.client.agent.list()

            payload: Any
            if isinstance(response, dict):
                payload = response
            elif hasattr(response, "model_dump"):
                payload = response.model_dump()
            elif hasattr(response, "dict"):
                payload = response.dict()
            else:
                payload = {"items": []}

            items = []
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = (
                    payload.get("agents")
                    or payload.get("items")
                    or payload.get("data")
                    or payload.get("results")
                    or []
                )
                if isinstance(items, dict):
                    items = (
                        items.get("agents")
                        or items.get("items")
                        or items.get("data")
                        or items.get("results")
                        or []
                    )

            normalized = []
            query = (search or "").strip().lower()
            for item in items:
                if not isinstance(item, dict):
                    continue
                agent_id = item.get("agent_id") or item.get("agentId") or item.get("id")
                if not agent_id:
                    continue
                name = item.get("agent_name") or item.get("name") or str(agent_id)
                if query and query not in str(name).lower():
                    continue
                normalized.append(
                    {
                        "id": str(agent_id),
                        "name": str(name),
                        "archived": bool(item.get("is_archived", False) or item.get("archived", False)),
                        "created_at": item.get("created_at"),
                        "metadata": item,
                    }
                )

            limited = normalized[: max(1, min(page_size, 100))]
            return {
                "agents": limited,
                "has_more": len(normalized) > len(limited),
                "next_cursor": None,
            }
        except Exception as e:
            raise ValueError(f"Failed to list Retell agents: {str(e)}")

    def extract_agent_prompt(self, agent_id: str) -> Optional[str]:
        """Extract the system prompt from a Retell agent.

        Handles all three response engine types:
        - retell-llm: fetch LLM by llm_id, read general_prompt
        - conversation-flow: fetch flow by conversation_flow_id, read global_prompt
        - custom-llm: no extractable prompt (websocket-based)
        """
        def _to_dict(obj: Any) -> Dict[str, Any]:
            if isinstance(obj, dict):
                return obj
            if hasattr(obj, "model_dump"):
                try:
                    dumped = obj.model_dump()
                    if isinstance(dumped, dict):
                        return dumped
                except Exception:
                    pass
            if hasattr(obj, "dict"):
                try:
                    dumped = obj.dict()
                    if isinstance(dumped, dict):
                        return dumped
                except Exception:
                    pass
            return {}

        def _first_non_empty(*values: Any) -> Optional[str]:
            for value in values:
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None

        def _extract_prompt_like(value: Any, visited: Optional[Set[int]] = None) -> Optional[str]:
            """Recursively search common prompt/instruction keys across dict/list payloads."""
            if visited is None:
                visited = set()
            obj_id = id(value)
            if obj_id in visited:
                return None
            visited.add(obj_id)

            if isinstance(value, str):
                cleaned = value.strip()
                return cleaned if cleaned else None

            if isinstance(value, dict):
                exact_keys = [
                    "general_prompt",
                    "generalPrompt",
                    "global_prompt",
                    "globalPrompt",
                    "system_prompt",
                    "systemPrompt",
                    "prompt",
                    "instructions",
                    "instruction",
                    "base_prompt",
                    "basePrompt",
                ]
                for key in exact_keys:
                    hit = value.get(key)
                    if isinstance(hit, str) and hit.strip():
                        return hit.strip()

                # Then recurse into likely nested prompt containers first.
                priority_nested_keys = [
                    "llm",
                    "model",
                    "config",
                    "settings",
                    "response_engine",
                    "responseEngine",
                    "conversation_flow",
                    "conversationFlow",
                ]
                for key in priority_nested_keys:
                    if key in value:
                        nested = _extract_prompt_like(value.get(key), visited)
                        if nested:
                            return nested

                # Finally search all values but prioritize keys that mention prompt/instruction.
                promptish_items = []
                other_items = []
                for key, nested_value in value.items():
                    key_lower = str(key).lower()
                    if any(token in key_lower for token in ("prompt", "instruction", "system")):
                        promptish_items.append(nested_value)
                    else:
                        other_items.append(nested_value)
                for nested_value in promptish_items:
                    nested = _extract_prompt_like(nested_value, visited)
                    if nested:
                        return nested
                for nested_value in other_items:
                    if isinstance(nested_value, (dict, list)):
                        nested = _extract_prompt_like(nested_value, visited)
                        if nested:
                            return nested
                return None

            if isinstance(value, list):
                for item in value:
                    nested = _extract_prompt_like(item, visited)
                    if nested:
                        return nested
                return None

            return None

        try:
            agent_response = self.client.agent.retrieve(agent_id=agent_id)
            agent_payload = _to_dict(agent_response)

            response_engine = getattr(agent_response, "response_engine", None)
            if response_engine is None:
                response_engine = agent_payload.get("response_engine")
            response_engine_payload = _to_dict(response_engine)

            # Fast path: many Retell agent payloads already include prompt-like fields.
            prompt = _first_non_empty(
                response_engine_payload.get("general_prompt"),
                response_engine_payload.get("system_prompt"),
                response_engine_payload.get("prompt"),
                agent_payload.get("general_prompt"),
                agent_payload.get("system_prompt"),
                agent_payload.get("prompt"),
            )
            if not prompt:
                prompt = _extract_prompt_like(response_engine_payload) or _extract_prompt_like(agent_payload)
            if prompt:
                return prompt

            engine_type = getattr(response_engine, "type", None)
            if isinstance(response_engine, dict) or response_engine_payload:
                engine_type = response_engine_payload.get("type", engine_type)

            logger.debug(f"[RetellProvider] response_engine type={engine_type}")

            # --- retell-llm: fetch the LLM and read general_prompt ---
            llm_id = getattr(response_engine, "llm_id", None)
            if isinstance(response_engine, dict) or response_engine_payload:
                llm_id = response_engine_payload.get("llm_id", llm_id)

            if llm_id:
                try:
                    logger.debug(f"[RetellProvider] Fetching LLM {llm_id}")
                    llm_response = self.client.llm.retrieve(llm_id=llm_id)
                    llm_payload = _to_dict(llm_response)
                    prompt = _first_non_empty(
                        getattr(llm_response, "general_prompt", None),
                        llm_payload.get("general_prompt"),
                        llm_payload.get("system_prompt"),
                        llm_payload.get("prompt"),
                        llm_payload.get("generalPrompt"),
                        llm_payload.get("systemPrompt"),
                    )
                    if not prompt:
                        prompt = _extract_prompt_like(llm_payload)
                    if prompt:
                        return prompt
                    logger.warning(f"[RetellProvider] LLM {llm_id} returned no prompt fields")
                except Exception as llm_exc:
                    logger.warning(f"[RetellProvider] Failed LLM prompt lookup for {llm_id}: {llm_exc}")

            # --- conversation-flow: fetch the flow and read global_prompt ---
            flow_id = getattr(response_engine, "conversation_flow_id", None)
            if isinstance(response_engine, dict) or response_engine_payload:
                flow_id = response_engine_payload.get("conversation_flow_id", flow_id)

            if flow_id:
                try:
                    logger.debug(f"[RetellProvider] Fetching conversation flow {flow_id}")
                    flow_response = self.client.conversation_flow.retrieve(
                        conversation_flow_id=flow_id
                    )
                    flow_payload = _to_dict(flow_response)
                    prompt = _first_non_empty(
                        getattr(flow_response, "global_prompt", None),
                        flow_payload.get("global_prompt"),
                        flow_payload.get("system_prompt"),
                        flow_payload.get("prompt"),
                        flow_payload.get("globalPrompt"),
                        flow_payload.get("systemPrompt"),
                    )
                    if not prompt:
                        prompt = _extract_prompt_like(flow_payload)
                    if prompt:
                        return prompt
                    logger.warning(f"[RetellProvider] Conversation flow {flow_id} returned no prompt fields")
                except Exception as flow_exc:
                    logger.warning(f"[RetellProvider] Failed flow prompt lookup for {flow_id}: {flow_exc}")

            # --- custom-llm or unknown: final fallback ---
            return _first_non_empty(
                response_engine_payload.get("system_prompt"),
                response_engine_payload.get("prompt"),
                getattr(response_engine, "system_prompt", None),
                getattr(response_engine, "prompt", None),
            )

        except Exception as e:
            logger.warning(f"[RetellProvider] Failed to extract agent prompt: {e}")
            return None

    def update_agent_prompt(self, agent_id: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Update a Retell agent's system prompt.

        Retrieves the current agent to find its LLM configuration, then updates
        the prompt via the agent update endpoint.

        Args:
            agent_id: Retell agent ID
            system_prompt: New system prompt text

        Returns:
            Updated agent data from Retell
        """
        try:
            current = self.get_agent(agent_id)
            response_engine = current.get("response_engine") or {}

            llm_id = response_engine.get("llm_id")
            if llm_id:
                llm_response = self.client.llm.update(
                    llm_id=llm_id,
                    general_prompt=system_prompt,
                )
                if isinstance(llm_response, dict):
                    return llm_response
                elif hasattr(llm_response, "model_dump"):
                    return llm_response.model_dump()
                return {"llm_id": llm_id, "updated": True}

            update_response = self.client.agent.update(
                agent_id=agent_id,
                response_engine={
                    **response_engine,
                    "system_prompt": system_prompt,
                },
            )
            if isinstance(update_response, dict):
                return update_response
            elif hasattr(update_response, "model_dump"):
                return update_response.model_dump()
            return {"agent_id": agent_id, "updated": True}
        except Exception as e:
            raise ValueError(f"Failed to update Retell agent prompt: {str(e)}")

    def test_connection(self) -> bool:
        """
        Test Retell connection by attempting to list agents.
        """
        try:
            self.client.agent.list()
            return True
        except Exception as e:
            raise ValueError(f"Retell connection test failed: {str(e)}")

