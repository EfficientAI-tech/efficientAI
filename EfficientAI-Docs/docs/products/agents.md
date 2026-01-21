---
id: agents
title: Agents
sidebar_position: 1
---

# Agents

## What is an Agent?

In EfficientAI, the **Agent** is simply **Your Voice AI**. It's the robot or system you are building and want to test.

Think of it as the "Employee" you are training. You want to see how good this employee is at talking to customers.

## Setting up an Agent

To test your AI, you need to tell EfficientAI where to find it. You can do this in the "Agents" section of the dashboard.

You generally need to tell us:
*   **Name**: What do you call your bot? (e.g., "Support Bot V1")
*   **Call Type**: Does your bot take calls (Inbound) or make calls (Outbound)?
*   **Connection**: How do we talk to it? (Using a phone number, or a direct software header).

---

## Technical Details

For developers, an **Agent** represents the system under test (SUT). This is your Voice AI application, whether hosted on an external platform (retell AI, Vapi) or a custom internal solution.

### Configuration

Agents are registered in the system with the following properties:

| Property | Type | Description |
|---|---|---|
| `name` | String | Name of the agent. |
| `agent_id` | String | A unique 6-digit identifier used within EfficientAI. |
| `phone_number` | String | (Optional) The PSTN number to dial if testing via phone network. |
| `language` | Enum | The primary language the agent is expected to speak (`en`, `es`, etc.). |
| `call_type` | Enum | `inbound` (Agent receives calls) or `outbound` (Agent places calls). |
| `call_medium` | Enum | `phone_call` (PSTN) or `web_call` (VoIP/WebRTC). |

### Integration Types

Agents connect to the evaluation platform through one of three mutually exclusive methods:

1.  **Voice Bundle**: A comprehensive stack defining STT, LLM, and TTS providers.
2.  **AI Provider**: Direct reference to a generic AI provider configuration.
3.  **External Integration**: For third-party platforms like Retell or Vapi.
