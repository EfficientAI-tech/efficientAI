"""Shared kwargs for uvicorn.run / CLI parity with Docker."""

from __future__ import annotations

from app.config import settings


def uvicorn_server_header_enabled() -> bool:
    return not settings.SECURITY_OMIT_SERVER_HEADER


def uvicorn_run_extra_kwargs() -> dict:
    return {"server_header": uvicorn_server_header_enabled()}
