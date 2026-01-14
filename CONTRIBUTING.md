# Contributing to EfficientAI

<p align="center">
  <img src="./assets/Readme%20logo.gif" alt="EfficientAI Demo" width="800">
</p>

Thank you for your interest in contributing to **EfficientAI**! 🙌

We are building an open-source evaluation platform for Voice AI, and every contribution—whether it's code, documentation, or just an idea—helps us improve the platform for everyone.

---

## Ways to Contribute

### 💡 Supporting and Voting on Ideas

We use **GitHub Discussions** and **Issues** to collect feature ideas. You can help by:

1.  **Upvoting existing ideas**: Go to the [Issues](https://github.com/EfficientAI-tech/efficientAI/issues) or [Discussions](https://github.com/EfficientAI-tech/efficientAI/discussions) page and react with a 👍 on ideas you'd like to see implemented.
2.  **Commenting on ideas**: Share your use case or how a feature would help you.

> **Note:** For the full voting experience on features, GitHub OAuth needs to be activated. This feature is coming soon to our website.

### 🐛 Creating and Commenting on Issues

*   **Bug Reports**: Found a bug? Please create a [new issue](https://github.com/EfficientAI-tech/efficientAI/issues/new) with a clear title and description.
*   **Feature Requests**: Have an idea? Open an issue with the `enhancement` label.

#### Issue Labels

Use (or request) these labels for your issues:

**🧭 Roadmap & Status**
| Label | Description |
|---|---|
| `roadmap` | Part of the public EfficientAI product roadmap. Users can vote on these. |
| `under-discussion` | Feature or idea is being discussed, refined, or validated with users. |
| `planned` | Accepted into the roadmap and scheduled to be built. |
| `in-progress` | Currently being worked on by maintainers or contributors. |
| `done` | Implemented and released. |

**🎯 Product Area**
| Label | Description |
|---|---|
| `voice-eval` | Anything related to evaluating voice agents, conversations, or audio quality. |
| `latency` | Performance, response times, real-time and streaming related issues. |
| `quality` | Accuracy, hallucinations, scoring, grading, or conversation quality. |
| `reliability` | Stability, uptime, retries, error handling, and fault tolerance. |
| `compliance` | Security, privacy, PII, HIPAA, GDPR, call recording laws, etc. |
| `infra` | Databases, queues, workers, scaling, deployment, and infrastructure. |
| `frontend` | Web UI, dashboards, charts, and user experience. |
| `api` | Public APIs, SDKs, webhooks, and integrations. |

**🛠 Contribution Level**
| Label | Description |
|---|---|
| `good-first-issue` | Small, well-scoped task ideal for first-time contributors. |
| `help-wanted` | Maintainers are actively looking for community help. |
| `core` | Deep architectural or product-critical work. |

**🧪 Use Case**
| Label | Description |
|---|---|
| `call-centers` | Features specifically useful for call center and BPO workflows. |
| `sales` | Voice agents for sales, lead qualification, or outbound calling. |
| `support` | Customer support voice bots and QA. |
| `healthcare` | Medical, HIPAA-sensitive, or healthcare voice use cases. |
| `agents` | General AI agent platforms and frameworks. |

---

## Submitting a Pull Request (PR)

We gratefully accept Pull Requests! To get your PR merged smoothly, please follow this format:

### PR Title Format

```
[type]: Short, descriptive title
```

Where `[type]` is one of:

*   `feat`: A new feature
*   `fix`: A bug fix
*   `docs`: Documentation only changes
*   `style`: Changes that do not affect the meaning of the code (formatting, etc.)
*   `refactor`: A code change that neither fixes a bug nor adds a feature
*   `test`: Adding missing tests or correcting existing tests
*   `chore`: Changes to the build process or auxiliary tools
*   `perf`: A code change that improves performance
*   `ci`: Changes to the CI/CD pipeline
*   `Integration`: Adding an Integration with an external service
*   `release`: A release or version change
*   `security`: A security fix

**Example:**
```
feat: Add support for multi-language personas
fix: Correct latency calculation for long audio files
docs: Improve CONTRIBUTING.md with PR format instructions
```

### PR Description

Your PR description **must** include the following sections:

```markdown
## What Changed?
A short summary of what this PR does.

## Why?
Explain the motivation or the problem being solved.

## How to Test?
Step-by-step instructions for reviewers to test your changes.

## Checklist
- [ ] I have read the `CONTRIBUTING.md` guide.
- [ ] My code follows the project's style guidelines.
- [ ] I have added tests that prove my fix is effective or my feature works.
- [ ] I have updated the documentation (if applicable).
```

### Documentation Contributions

We gratefully accept any documentation improvements! If you have corrections, clarifications, or entirely new guides, please submit a PR with `docs:` prefix.

---

## Join the Community

Have questions or want to chat? Join our Discord community:

➡️ **Join Discord**: [https://discord.gg/bw957xEk](https://discord.gg/bw957xEk)

---

## Project Overview

EfficientAI is a comprehensive platform designed to evaluate and improve Voice AI agents. It closes the feedback loop by simulating real-world conversations using AI-driven test agents (Personas) and Scenarios, and then rigorously evaluating the performance using a suite of quantitative and qualitative metrics.

### Tech Stack

| Category | Technology |
|---|---|
| **Backend** | Python 3.11+, FastAPI |
| **Database** | PostgreSQL, SQLAlchemy (ORM), Alembic (Migrations) |
| **Task Queue** | Celery, Redis |
| **Audio Processing** | Whisper, Librosa, SoundFile, Pydub |
| **AI Services** | OpenAI, Retell SDK, Pipecat AI |
| **Frontend** | React, Vite |
| **Deployment** | Docker, Docker Compose |

### Architecture

The platform consists of several core components:

1.  **Voice AI Integration**: Connects to external Voice AI providers (e.g., Retell, Vapi) or manages internal models.
2.  **Test Agents (Personas)**: Simulated users with specific attributes (accent, gender, background noise) that interact with the Voice AI.
3.  **Scenarios**: Defined conversation paths and objectives that the Test Agent attempts to follow or achieve.
4.  **Orchestrator**: Manages the live conversation between the Voice AI and the Test Agent, handling audio streaming, transcription, and response generation.
5.  **Evaluators**: Post-conversation analysis metrics that assess the Voice AI's performance based on the specific scenario benchmarks.

---

## Database Overview

The database is managed via SQLAlchemy. Below is a simplified view of the core tables:

| Table | Description |
|---|---|
| `organizations` | Multi-tenancy support for different teams. |
| `users` | User authentication and profiles. |
| `agents` | The Voice AI system under test. |
| `personas` | The simulated caller/user for testing. |
| `scenarios` | The conversation scenario/test case. |
| `evaluators` | Bind Agent + Persona + Scenario for a test run. |
| `evaluator_results` | Stores evaluation results, transcripts, and metric scores. |
| `metrics` | Configuration for evaluation metrics. |
| `voicebundles` | Composable unit of STT + LLM + TTS. |

For the full schema, see the ER diagram in the repository: `schema_er_diagram.png`.

---

## Repository Structure

```
efficientAI/
├── app/                    # Backend application (FastAPI)
│   ├── api/                # API routes
│   ├── core/               # Core utilities (auth, config, exceptions)
│   ├── models/             # SQLAlchemy database models
│   ├── services/           # Business logic services
│   ├── workers/            # Celery background tasks
│   └── main.py             # FastAPI application entry point
├── frontend/               # Frontend application (React + Vite)
├── migrations/             # Database migration scripts
├── scripts/                # Utility scripts
├── tests/                  # Test suite
├── docker/                 # Docker configurations
├── docker-compose.yml      # Docker Compose orchestration
├── pyproject.toml          # Python project configuration
├── config.yml.example      # Example configuration file
└── README.md               # Main documentation
```

---

## Development Setup

### Requirements

*   **Python**: 3.11+ (as specified in `.nvmrc` or `pyproject.toml`)
*   **Node.js**: 18+ and npm
*   **Docker**: To run the database and Redis locally
*   **PostgreSQL**: Running locally or remote
*   **Redis**: Running locally or remote

### Steps

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/EfficientAI-tech/efficientAI.git
    cd efficientAI
    ```

2.  **Create a virtual environment and install dependencies:**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -e ".[dev]"
    ```

3.  **Install frontend dependencies:**

    ```bash
    cd frontend
    npm install
    cd ..
    ```

4.  **Create an env file:**

    ```bash
    cp env.example .env
    cp config.yml.example config.yml
    ```

    Edit `config.yml` with your database and Redis connection strings.

5.  **Start PostgreSQL and Redis (using Docker):**

    ```bash
    docker compose up -d db redis
    ```

6.  **Run the application:**

    ```bash
    # Start both API server and Celery worker
    eai start-all --config config.yml
    ```

    Access the app at: `http://localhost:8000`

### Running Tests

```bash
pytest
```

---

## Code Style

*   **Linting**: We use `ruff` for Python linting.
*   **Formatting**: We use `black` for Python formatting (line-length: 100).
*   **Type Checking**: We use `mypy` for type hints.

Before submitting a PR, run:

```bash
ruff check .
black --check .
mypy .
```

---

## CI/CD

We use GitHub Actions for CI/CD. The configuration is in `.github/workflows/`.

*   **CI on `main` and Pull Requests**:
    *   Check Linting
    *   Run Tests
*   **CD on `main`**:
    *   Publish Docker image to GitHub Packages (if CI passes).

---

Thank you again for contributing! We appreciate your time and effort. 💚
