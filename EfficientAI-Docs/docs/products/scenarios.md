---
id: scenarios
title: Scenarios
sidebar_position: 3
---

# Scenarios

A Scenario defines the goal and context for a test conversation.

## How scenarios are created

EfficientAI supports three scenario creation paths:

1. **Generate from Agent Prompt (AI-assisted)**  
   Generate scenario drafts from the selected agent's prompt/description.
2. **Generate from Call data**  
   Derive scenario content from call transcripts or call data.
3. **Create Manually**  
   Write a fully custom scenario.

```mermaid
flowchart LR
    P[Agent Prompt] --> G1[Generate Scenario Draft]
    C[Call Transcripts or Call Data] --> G2[Generate Scenario Draft]
    M[Manual Authoring] --> G3[Custom Scenario]
    G1 --> Final[Scenario Library]
    G2 --> Final
    G3 --> Final
```

## Scenario structure

| Field | Description |
|---|---|
| `name` | Scenario title. |
| `description` | What should happen in the conversation. |
| `required_info` | Structured key/value expectations for the test. |
| `agent_id` | Optional linked agent for context. |

## How scenarios are used

Scenarios are used to:

- guide persona behavior during tests,
- provide evaluation context for scoring,
- keep testing reproducible across repeated runs.

A good scenario is specific enough to be measurable, but open enough to preserve natural conversation flow.
