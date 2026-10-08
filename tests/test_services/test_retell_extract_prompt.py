"""Retell prompt import for chat/voice agents (conversation flow + retell-llm)."""

from app.services.voice_providers.retell import (
    RetellVoiceProvider,
    _retell_prompt_from_conversation_flow,
    _retell_prompt_from_llm_payload,
)


def test_retell_prompt_from_llm_general_and_states():
    prompt = _retell_prompt_from_llm_payload(
        {
            "general_prompt": "Base instructions",
            "states": [{"state_prompt": "Collect name and email."}],
        }
    )
    assert "Base instructions" in prompt
    assert "Collect name" in prompt


def test_retell_extract_conversation_flow_global_prompt(monkeypatch):
    class _FlowAPI:
        def retrieve(self, **kwargs):
            assert kwargs["conversation_flow_id"] == "flow_abc"
            return {"global_prompt": "You are a chat assistant for bookings."}

    class _AgentAPI:
        def retrieve(self, agent_id):
            return {
                "agent_id": agent_id,
                "response_engine": {
                    "type": "conversation-flow",
                    "conversation_flow_id": "flow_abc",
                    "version": 2,
                },
            }

    class _FakeClient:
        agent = _AgentAPI()
        conversation_flow = _FlowAPI()
        llm = None

    provider = RetellVoiceProvider.__new__(RetellVoiceProvider)
    provider.client = _FakeClient()

    assert (
        provider.extract_agent_prompt("agent_chat_1")
        == "You are a chat assistant for bookings."
    )


def test_retell_extract_llm_after_empty_flow(monkeypatch):
    class _FlowAPI:
        def retrieve(self, **kwargs):
            return {"global_prompt": "", "nodes": []}

    class _LlmAPI:
        def retrieve(self, llm_id):
            assert llm_id == "llm_1"
            return {"general_prompt": "From retell LLM"}

    class _AgentAPI:
        def retrieve(self, agent_id):
            return {
                "agent_id": agent_id,
                "response_engine": {
                    "type": "conversation-flow",
                    "conversation_flow_id": "flow_abc",
                    "llm_id": "llm_1",
                },
            }

    class _FakeClient:
        agent = _AgentAPI()
        conversation_flow = _FlowAPI()
        llm = _LlmAPI()

    provider = RetellVoiceProvider.__new__(RetellVoiceProvider)
    provider.client = _FakeClient()

    assert provider.extract_agent_prompt("agent_1") == "From retell LLM"


def test_retell_extract_uses_chat_agent_api_for_chat_channel():
    class _FlowAPI:
        def retrieve(self, **kwargs):
            return {"global_prompt": "Chat global prompt from flow."}

    class _ChatAgentAPI:
        def retrieve(self, agent_id):
            assert agent_id == "chat_agent_1"
            return {
                "agent_id": agent_id,
                "channel": "chat",
                "response_engine": {
                    "type": "conversation-flow",
                    "conversation_flow_id": "flow_chat",
                    "version": 1,
                },
            }

    class _VoiceAgentAPI:
        def retrieve(self, agent_id):
            raise ValueError("voice agent not found")

    class _FakeClient:
        agent = _VoiceAgentAPI()
        chat_agent = _ChatAgentAPI()
        conversation_flow = _FlowAPI()
        llm = None

    provider = RetellVoiceProvider.__new__(RetellVoiceProvider)
    provider.client = _FakeClient()

    assert (
        provider.extract_agent_prompt("chat_agent_1", agent_channel="chat")
        == "Chat global prompt from flow."
    )


def test_retell_extract_flow_nodes_when_global_empty():
    flow = {
        "global_prompt": "",
        "nodes": [
            {"instruction": {"type": "prompt", "prompt": "Greet and ask how you can help."}},
        ],
    }
    assert _retell_prompt_from_conversation_flow(flow) == "Greet and ask how you can help."
