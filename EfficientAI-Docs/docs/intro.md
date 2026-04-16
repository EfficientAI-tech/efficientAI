---
id: intro
title: Introduction
sidebar_position: 1
---

# Introduction

EfficientAI is a voice AI evaluation platform for testing, measuring, and improving conversational agents before they reach production.

It helps teams run realistic simulations, analyze outcomes with explicit metrics, and iterate quickly on agent behavior, prompts, and voice quality.

## What the platform does

EfficientAI gives you an end-to-end loop for voice AI quality:

1. Configure the **Agent** you want to test.
2. Configure **Personas** with mapped voices for caller simulation.
3. Define **Scenarios** that represent conversation goals.
4. Run tests in the **Agent Playground** or evaluator workflows.
5. Score calls using enabled **Metrics**.
6. Improve prompts and re-test to track quality over time.

## Core capabilities

- **Agent testing across call setups**: supports inbound/outbound context and phone/web call mediums.
- **Prompt management**: maintain an internal test-agent prompt and sync provider prompts from external voice platforms.
- **Voice bundle composition**: configure STT, LLM, and TTS stacks (or S2S where configured) for test-agent behavior.
- **Persona voice mapping**: personas are tied to concrete provider and voice identities.
- **Scenario generation and curation**: generate from agent prompts, derive from call transcripts/call data, or create manually.
- **Metric-driven evaluation**: enable the exact metrics you want and apply them consistently across runs.
- **Prompt optimization workflows**: run optimization loops, compare candidates, accept winners, and push selected prompts to providers.

## Platform model

At a high level:

- **Agents** are the systems under test.
- **Personas** represent simulated callers with specific voice identities.
- **Scenarios** define goals and test context.
- **Metrics** evaluate objective completion and voice quality.
- **Results** provide run-level evidence for iteration decisions.

This structure keeps testing reproducible while still reflecting real-world voice interactions.
