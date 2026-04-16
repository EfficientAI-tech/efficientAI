---
id: agents
title: Agents
sidebar_position: 1
---

# Agents

An Agent is the voice system you are evaluating in EfficientAI.

## Agent paths in practice

An agent can be configured for one or both execution paths:

- **Test Agent path (internal)**: uses an EfficientAI voice bundle to run STT -> LLM -> TTS behavior.
- **Voice AI Agent path (external)**: links to an external voice provider agent, such as Retell, Vapi, or ElevenLabs.

If both are configured, you can test both paths from the Agent Playground.

## Core configuration

| Property | Type | Description |
|---|---|---|
| `name` | String | Human-readable agent name. |
| `language` | Enum | Primary language context for evaluation. |
| `call_type` | Enum | `inbound` or `outbound` behavior context. |
| `call_medium` | Enum | `phone_call` or `web_call`. |
| `phone_number` | String | Required when `call_medium = phone_call`. |
| `voice_bundle_id` | UUID | Internal test stack for voice-bundle testing. |
| `voice_ai_integration_id` | UUID | External provider integration reference. |
| `voice_ai_agent_id` | String | External provider agent identifier. |

## Inbound vs outbound calls

Use `call_type` to model the call direction your production agent is designed for:

- **Inbound**: user initiates call to the agent.
- **Outbound**: agent initiates call to the user.

This setting should match your real deployment pattern so evaluation conditions are realistic.

## Prompt management

Agents can carry two prompt surfaces:

- **EfficientAI Test Agent Description (`description`)**  
  Internal prompt used for test-agent behavior and evaluation context.
- **Provider Prompt (`provider_prompt`)**  
  Prompt fetched from the linked external voice provider.

### Provider prompt sync

When an agent is linked to an external provider, EfficientAI can fetch and store the current provider prompt.

Sync can happen:

- automatically on relevant create/update operations, and
- manually through "Sync Now" in the agent view.

This keeps local review and optimization aligned with what is currently running on the provider.

## Voice bundles

Voice bundles define how internal test-agent conversations are generated.

Supported bundle types:

- **STT + LLM + TTS**
- **S2S** (speech-to-speech)

For STT + LLM + TTS bundles, model/provider settings are configured per stage, including optional LLM temperature and max token controls.

## External voice integrations

For live external testing, configure:

1. `voice_ai_integration_id`
2. `voice_ai_agent_id`
3. `call_medium = web_call` for Agent Playground web calls

This enables real-time provider calls and evaluation flow from provider call data into EfficientAI results.
