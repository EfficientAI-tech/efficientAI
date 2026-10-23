"""Harbor-powered simulation runs (test agent ↔ production agent).

Only ``conversation_agent``, ``metric_verifier``, ``noop_environment`` and
``job_runner`` import ``harbor``; they run inside the worker-harbor process.
The remaining modules are dependency-free so the API can import them.
"""
