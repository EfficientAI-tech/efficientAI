"""
Retell Voice Provider Implementation
Handles integration with Retell AI voice agents
"""
from typing import Dict, Any, Optional, List
from retell import Retell
from loguru import logger

from app.services.voice_providers.base import BaseVoiceProvider


def _retell_agent_list_page(raw: Any) -> tuple[List[Any], bool, Optional[str]]:
    """Retell SDK v5+ returns AgentListResponse { items, has_more, pagination_key }, not a bare list."""
    if isinstance(raw, list):
        return raw, False, None
    if hasattr(raw, "model_dump"):
        try:
            raw = raw.model_dump()
        except Exception:
            pass
    elif hasattr(raw, "dict"):
        try:
            raw = raw.dict()
        except Exception:
            pass
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("agents") or []
        return (
            list(items) if isinstance(items, list) else [],
            bool(raw.get("has_more")),
            raw.get("pagination_key"),
        )
    items = getattr(raw, "items", None) or getattr(raw, "agents", None) or []
    return (
        list(items) if isinstance(items, list) else [],
        bool(getattr(raw, "has_more", False)),
        getattr(raw, "pagination_key", None),
    )


def _retell_sdk_to_dict(raw: Any) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            dumped = raw.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    if hasattr(raw, "dict"):
        try:
            dumped = raw.dict()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    return None


def _retell_nonempty_prompt(*candidates: Any) -> Optional[str]:
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _retell_prompt_from_llm_payload(llm: dict[str, Any]) -> Optional[str]:
    general = _retell_nonempty_prompt(llm.get("general_prompt"))
    state_parts: list[str] = []
    states = llm.get("states")
    if isinstance(states, list):
        for state in states:
            if not isinstance(state, dict):
                continue
            part = _retell_nonempty_prompt(state.get("state_prompt"))
            if part:
                state_parts.append(part)
    if general and state_parts:
        return f"{general}\n\n" + "\n\n".join(state_parts)
    if general:
        return general
    if state_parts:
        return "\n\n".join(state_parts)
    return _retell_nonempty_prompt(
        llm.get("system_prompt"),
        llm.get("prompt"),
    )


def _retell_normalize_engine_type(raw: Any) -> str:
    return str(raw or "").strip().lower().replace("_", "-")


def _retell_agent_direct_prompt(agent: dict[str, Any]) -> Optional[str]:
    return _retell_nonempty_prompt(
        agent.get("general_prompt"),
        agent.get("global_prompt"),
        agent.get("system_prompt"),
        agent.get("prompt"),
    )


def _retell_prompt_from_flow_nodes(flow: dict[str, Any]) -> Optional[str]:
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        return None
    chunks: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        instruction = node.get("instruction")
        if isinstance(instruction, str):
            part = _retell_nonempty_prompt(instruction)
            if part:
                chunks.append(part)
                continue
        if isinstance(instruction, dict):
            part = _retell_nonempty_prompt(
                instruction.get("prompt"),
                instruction.get("text"),
            )
            if part:
                chunks.append(part)
                continue
        part = _retell_nonempty_prompt(
            node.get("global_prompt"),
            node.get("prompt"),
            node.get("text"),
        )
        if part:
            chunks.append(part)
    if not chunks:
        return None
    return "\n\n".join(chunks)


def _retell_prompt_from_conversation_flow(flow: dict[str, Any]) -> Optional[str]:
    prompt = _retell_nonempty_prompt(flow.get("global_prompt"))
    if prompt:
        return prompt
    from_nodes = _retell_prompt_from_flow_nodes(flow)
    if from_nodes:
        return from_nodes
    components = flow.get("components")
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            nested = _retell_prompt_from_conversation_flow(component)
            if nested:
                return nested
            part = _retell_prompt_from_flow_nodes(component)
            if part:
                return part
    return None


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
    
    def _retrieve_voice_agent_record(self, agent_id: str) -> Optional[dict[str, Any]]:
        try:
            agent_response = self.client.agent.retrieve(agent_id=agent_id)
            return _retell_sdk_to_dict(agent_response)
        except Exception as exc:
            logger.debug("[RetellProvider] agent.retrieve failed for {}: {}", agent_id, exc)
            return None

    def _retrieve_chat_agent_record(self, agent_id: str) -> Optional[dict[str, Any]]:
        chat_api = getattr(self.client, "chat_agent", None)
        if chat_api is None:
            return None
        try:
            agent_response = chat_api.retrieve(agent_id=agent_id)
            record = _retell_sdk_to_dict(agent_response)
            if record is not None:
                record.setdefault("agent_id", agent_id)
                record["channel"] = "chat"
            return record
        except Exception as exc:
            logger.debug("[RetellProvider] chat_agent.retrieve failed for {}: {}", agent_id, exc)
            return None

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get Retell voice or chat agent details."""
        voice = self._retrieve_voice_agent_record(agent_id)
        if voice:
            return voice
        chat = self._retrieve_chat_agent_record(agent_id)
        if chat:
            return chat
        raise ValueError(f"Failed to get Retell agent: {agent_id}")
    
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

    def _retrieve_conversation_flow_once(
        self,
        flow_id: str,
        version: Any,
    ) -> Optional[dict[str, Any]]:
        retrieve_kwargs: dict[str, Any] = {"conversation_flow_id": flow_id}
        if version is not None:
            retrieve_kwargs["version"] = version
        try:
            flow_response = self.client.conversation_flow.retrieve(**retrieve_kwargs)
            return _retell_sdk_to_dict(flow_response) or {}
        except Exception as exc:
            logger.debug(
                "[RetellProvider] conversation_flow.retrieve {} version={}: {}",
                flow_id,
                version,
                exc,
            )
            return None

    def _retrieve_conversation_flow(self, flow_id: str, version: Any) -> Optional[dict[str, Any]]:
        versions_to_try: list[Any] = []
        if version is not None:
            versions_to_try.append(version)
            try:
                versions_to_try.append(int(version))
            except (TypeError, ValueError):
                pass
            try:
                versions_to_try.append(float(version))
            except (TypeError, ValueError):
                pass
        versions_to_try.append(None)
        seen: set[str] = set()
        for ver in versions_to_try:
            key = repr(ver)
            if key in seen:
                continue
            seen.add(key)
            flow = self._retrieve_conversation_flow_once(flow_id, ver)
            if flow:
                prompt = _retell_prompt_from_conversation_flow(flow)
                if prompt or flow.get("global_prompt") is not None or flow.get("nodes"):
                    return flow
        return None

    def _extract_prompt_from_agent_record(
        self,
        agent: dict[str, Any],
        agent_id: str,
    ) -> Optional[str]:
        direct = _retell_agent_direct_prompt(agent)
        if direct:
            return direct

        response_engine = _retell_sdk_to_dict(agent.get("response_engine"))
        if not response_engine:
            logger.warning("[RetellProvider] No response_engine on agent {}", agent_id)
            return None

        engine_type = _retell_normalize_engine_type(response_engine.get("type"))
        logger.debug("[RetellProvider] agent {} response_engine type={}", agent_id, engine_type)

        flow_id = (
            response_engine.get("conversation_flow_id")
            or response_engine.get("conversation_flow")
            or agent.get("conversation_flow_id")
            or ""
        )
        flow_id = str(flow_id).strip()
        llm_id = str(response_engine.get("llm_id") or "").strip()

        if flow_id:
            logger.debug("[RetellProvider] Fetching conversation flow {}", flow_id)
            version = response_engine.get("version")
            flow = self._retrieve_conversation_flow(flow_id, version)
            if flow:
                prompt = _retell_prompt_from_conversation_flow(flow)
                if prompt:
                    return prompt
            logger.warning(
                "[RetellProvider] Conversation flow {} returned no global_prompt or node prompts",
                flow_id,
            )

        if llm_id:
            logger.debug("[RetellProvider] Fetching LLM {}", llm_id)
            llm_response = self.client.llm.retrieve(llm_id=llm_id)
            llm = _retell_sdk_to_dict(llm_response) or {}
            prompt = _retell_prompt_from_llm_payload(llm)
            if prompt:
                return prompt
            logger.warning("[RetellProvider] LLM {} returned no general/state prompt", llm_id)

        prompt = _retell_nonempty_prompt(
            response_engine.get("general_prompt"),
            response_engine.get("global_prompt"),
            response_engine.get("system_prompt"),
        )
        if prompt:
            return prompt

        if engine_type == "custom-llm":
            logger.warning("[RetellProvider] custom-llm agents have no importable prompt")
        return None

    def extract_agent_prompt(
        self,
        agent_id: str,
        *,
        agent_channel: Optional[str] = None,
    ) -> Optional[str]:
        """Extract the system prompt from a Retell voice or chat agent."""
        channel = (agent_channel or "").strip().lower()
        voice_record = self._retrieve_voice_agent_record(agent_id)
        chat_record = self._retrieve_chat_agent_record(agent_id)
        if channel == "chat":
            records = [chat_record, voice_record]
        else:
            records = [voice_record, chat_record]

        try:
            for agent in records:
                if not agent:
                    continue
                prompt = self._extract_prompt_from_agent_record(agent, agent_id)
                if prompt:
                    return prompt
            return None
        except Exception as e:
            logger.warning("[RetellProvider] Failed to extract agent prompt for {}: {}", agent_id, e)
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
            self.client.agent.list(limit=1)
            return True
        except Exception as e:
            raise ValueError(f"Retell connection test failed: {str(e)}")

    def _list_agents_by_channel(
        self,
        *,
        channel: str,
        search: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """POST /v2/list-agents via SDK with filter_criteria.channel (voice | chat)."""
        list_filter = {
            "filter_criteria": {
                "channel": {"type": "string", "op": "eq", "value": channel},
            },
        }
        collected: List[Any] = []
        pagination_key: Optional[str] = None
        for _ in range(50):
            list_params: Dict[str, Any] = {"limit": 100, **list_filter}
            if pagination_key:
                list_params["pagination_key"] = pagination_key
            raw = self.client.agent.list(**list_params)
            page_items, has_more, pagination_key = _retell_agent_list_page(raw)
            collected.extend(page_items)
            if not has_more or not pagination_key:
                break

        agents: List[Dict[str, str]] = []
        needle = (search or "").strip().lower()
        for item in collected:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            elif hasattr(item, "dict"):
                item = item.dict()
            if not isinstance(item, dict):
                continue
            agent_id = str(
                item.get("agent_id") or item.get("chat_agent_id") or item.get("id") or ""
            ).strip()
            if not agent_id:
                continue
            name = str(
                item.get("agent_name") or item.get("name") or item.get("chat_agent_name") or agent_id
            ).strip()
            item_channel = str(item.get("channel") or "").strip().lower()
            if item_channel in ("voice", "chat") and item_channel != channel:
                continue
            if channel == "chat" and item_channel == "chat" and "chat" not in name.lower():
                name = f"{name} · chat"
            if needle and needle not in name.lower() and needle not in agent_id.lower():
                continue
            agents.append({"id": agent_id, "name": name})
        agents.sort(key=lambda row: row["name"].lower())
        return agents

    def list_agents(self, *, search: Optional[str] = None) -> List[Dict[str, str]]:
        """List Retell voice-channel agents (web/phone calls)."""
        try:
            return self._list_agents_by_channel(channel="voice", search=search)
        except Exception as e:
            raise ValueError(f"Failed to list Retell agents: {str(e)}") from e

    def list_chat_agents(self, *, search: Optional[str] = None) -> List[Dict[str, str]]:
        """List Retell chat-channel agents (required for /create-chat)."""
        try:
            return self._list_agents_by_channel(channel="chat", search=search)
        except Exception as e:
            raise ValueError(f"Failed to list Retell chat agents: {str(e)}") from e

