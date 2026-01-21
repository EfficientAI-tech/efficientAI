---
id: intro
title: Introduction
sidebar_position: 1
---

# Introduction

## What is EfficientAI?

Think of **EfficientAI** as a high-tech training gym for your Voice AI.

Building a Voice AI (like a customer service bot) is hard. You don't want to test it on real customers until you are sure it works perfectly. EfficientAI lets you practice by having **simulated customers** (robots pretending to be people) call your AI and test it out.

We help you answer questions like:
*   "Can my AI understand a thick accent?"
*   "Does my AI stay calm when the customer is angry?"
*   "Is my AI fast enough?"

## How does it work?

Imagine you are hiring a new customer support agent. Before letting them answer real calls, you would role-play with them. You might pretend to be an angry customer with a broken product to see how they handle it.

EfficientAI automates this role-play:

1.  **The Employee (Agent)**: This is your Voice AI that you are building.
2.  **The Actor (Persona)**: We have a robot caller that pretends to differnt people—like "Bob from Texas" or "Alice from London".
3.  **The Script (Scenario)**: You give the Actor a secret mission, like "Call and try to return a pair of shoes without a receipt."
4.  **The Scorecard (Evaluator)**: After the call, we grade your AI. Did it solve the problem? Was it polite? Did it understand what the Actor said?

## Why use it?

*   **Save Money**: Don't waste your team's time manually calling your bot 100 times.
*   **Find Bugs**: Catch problems before your real customers do.
*   **Improve Quality**: See exactly where your AI is struggling so you can fix it.

---

## Technical Overview

For developers and engineers, EfficientAI is a comprehensive platform designed to evaluate and improve Voice AI agents. It effectively closes the feedback loop by simulating real-world conversations using AI-driven test agents (Personas) and Scenarios, and then rigorously evaluating the performance using a suite of quantitative and qualitative metrics.

### High-Level Architecture

The platform consists of several core components that work together to automate the testing and evaluation process:

1.  **Voice AI Integration**: Connects to external Voice AI providers (e.g., Retell, Vapi) or manages internal models.
2.  **Test Agents (Personas)**: Simulated users with specific attributes (accent, gender, background noise) that interact with the Voice AI.
3.  **Scenarios**: Defined conversation paths and objectives that the Test Agent attempts to follow or achieve.
4.  **Orchestrator**: Manages the live conversation between the Voice AI and the Test Agent, handling audio streaming, transcription, and response generation.
5.  **Evaluators**: Post-conversation analysis metrics that assess the Voice AI's performance based on the specific scenario benchmarks.
