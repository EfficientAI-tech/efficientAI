#!/usr/bin/env python3
"""Export FastAPI OpenAPI schema for docs static generation."""

from __future__ import annotations

import json
import os
import sys
import types
import importlib.metadata as importlib_metadata
from pathlib import Path


def _ensure_email_validator_module() -> None:
    """Provide a tiny shim when email-validator is unavailable."""
    try:
        import email_validator  # type: ignore # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    shim = types.ModuleType("email_validator")
    shim.__version__ = "2.0.0"

    class EmailNotValidError(ValueError):
        pass

    def validate_email(value: str, *_args, **_kwargs):
        local, _, domain = value.partition("@")
        if not local or not domain:
            raise EmailNotValidError("invalid email")
        return types.SimpleNamespace(email=value, normalized=value, local_part=local, domain=domain)

    shim.EmailNotValidError = EmailNotValidError
    shim.validate_email = validate_email
    sys.modules["email_validator"] = shim

    original_version = importlib_metadata.version

    def _version(package_name: str) -> str:
        if package_name == "email-validator":
            return "2.0.0"
        return original_version(package_name)

    importlib_metadata.version = _version


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    docs_root = repo_root / "docs-fumadocs"
    output_file = docs_root / "openapi" / "openapi.json"

    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("SERVICE_MODE", "api")
    os.environ.setdefault("UPLOAD_DIR", str(docs_root / ".openapi-export" / "uploads"))

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    _ensure_email_validator_module()

    from app.app_factory import create_app  # pylint: disable=import-outside-toplevel

    app = create_app()
    schema = app.openapi()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"Exported OpenAPI spec to {output_file}")


if __name__ == "__main__":
    main()
