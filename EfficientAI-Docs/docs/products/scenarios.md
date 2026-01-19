---
id: scenarios
title: Scenarios
sidebar_position: 3
---

# Scenarios

## What is a Scenario?

A **Scenario** is the "Script" or "Mission" for the call.

If the Persona is the *actor*, the Scenario tells them *what to do*. Without a scenario, the actor wouldn't know why they are calling.

Examples of Scenarios:
*   **"Book an Appointment"**: The caller wants to schedule a dentist visit for next Tuesday.
*   **"Return a Product"**: The caller is angry because their new toaster is broken and wants a refund.
*   **"Ask a Question"**: The caller simply wants to know your business hours.

EfficientAI gives this script to the simulated caller, and they will try to achieve their goal while talking to your AI.

---

## Technical Details

Scenarios define the objective of the conversation. They guide the Persona on what they need to achieve during the call, ensuring that the Test Agent challenges the Voice AI in specific, reproducible ways.

### Configuration

A Scenario consists of the following fields:

| Field | Type | Description |
|---|---|---|
| `name` | String | The name of the scenario. |
| `description` | String | A high-level description of what should happen. |
| `required_info` | JSON | A structured list of information the Persona **must** collect or convey during the call. |

### Required Info Structure

The `required_info` field is a JSON object that lists data points necessary for success. This is injected into the System Prompt.

**Example:**
```json
{
  "appointment_date": "next Tuesday",
  "appointment_time": "morning",
  "reason": "routine cleaning"
}
```

### Scenario Logic

The `TestAgentService` combines the Persona definition with the Scenario details to form a complete System Prompt, instructing the LLM to role-play the specific situation.
