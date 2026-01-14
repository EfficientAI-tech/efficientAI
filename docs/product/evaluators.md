---
id: evaluators
title: Evaluators
sidebar_position: 4
---

# Evaluators

## What is an Evaluator?

An **Evaluator** is a complete "Test Configuration". It brings everything together.

Think of it as scheduling a specific exam. To run a test, you need three things:
1.  **Student**: Which AI are we testing? (The **Agent**)
2.  **Actor**: Who is calling? (The **Persona**)
3.  **Test Question**: What is the call about? (The **Scenario**)

When you create an Evaluator in EfficientAI, you are simply linking these three things together. Once created, you can run this Evaluator anytime to start a test call.

---

## Technical Details

Evaluators are the configuration entities that bind an **Agent** to a specific **Persona** and **Scenario** for testing. They serve as the template for running reproducible tests.

### Definition

An Evaluator consists of:

| Field | Type | Description |
|---|---|---|
| `evaluator_id` | String | Unique 6-digit identifier. |
| `agent_id` | UUID | The Agent to be tested. |
| `persona_id` | UUID | The Persona to use for the test. |
| `scenario_id` | UUID | The Scenario to execute. |

### Execution Process

When an Evaluator is run:
1.  **Conversation**: The `TestAgentService` runs the conversation between the Agent and the Persona.
2.  **Recording**: The conversation is recorded and transcribed.
3.  **Result Generation**: An `EvaluatorResult` record is created.
4.  **Metric Calculation**: Post-conversation, systems calculate the metrics (WER, Latency, etc.).
