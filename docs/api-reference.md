---
id: api-reference
title: API Reference
sidebar_position: 10
---

# API Reference

EfficientAI exposes a comprehensive RESTful API for managing resources and programmatic control of evaluations.

**Base URL**: `http://localhost:8000/api/v1`

## Authentication

All API requests require authentication using an API Key.
Pass the key in the `X-API-Key` header.

```bash
curl -H "X-API-Key: your_api_key_here" http://localhost:8000/api/v1/agents
```

*(See `docs/guides/iam.md` for managing API keys)*

## Key Resources

### Agents
Manage the Voice AI systems under test.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/agents` | List all agents. |
| `POST` | `/agents` | Create a new agent configuration. |
| `GET` | `/agents/{id}` | Get details of a specific agent. |
| `PUT` | `/agents/{id}` | Update agent settings. |

### Personas
Manage the simulated user profiles.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/personas` | List available personas. |
| `POST` | `/personas` | Define a new persona (voice, accent, traits). |

### Scenarios
Manage test scripts and objectives.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/scenarios` | List scenarios. |
| `POST` | `/scenarios` | Create a new scenario with required info. |

### Evaluators & Results
Configure and retrieve tests.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/evaluators` | Create an evaluation configuration (Agent + Persona + Scenario). |
| `POST` | `/evaluators/{id}/run` | Trigger a run of an evaluator. |
| `GET` | `/results` | List past evaluation results. |
| `GET` | `/results/{id}` | Get detailed metrics and transcript for a result. |

### Test Agent Orchestration
Endpoints for live interaction.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/test-agents/conversation/start` | Initiate a new test conversation. |
| `POST` | `/test-agents/conversation/{id}/audio` | Stream audio chunks to the test agent. |
| `POST` | `/test-agents/conversation/{id}/end` | Terminate the conversation. |

## Interactive Documentation

EfficientAI bundles **Swagger UI** and **ReDoc** for interactive API exploration.
Once the server is running, visit:

*   **Swagger UI**: `http://localhost:8000/docs` - Try out endpoints directly in your browser.
*   **ReDoc**: `http://localhost:8000/redoc` - Alternative clean documentation view.
