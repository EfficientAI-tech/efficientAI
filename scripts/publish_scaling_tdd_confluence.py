#!/usr/bin/env python3
"""Publish docs/call-traces-scaling-tdd-confluence.md to Confluence page 76349452 (v2.0)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PAGE_ID = "76349452"
BASE = os.environ.get("CONFLUENCE_BASE_URL", "https://efficientai.atlassian.net").rstrip("/")
EMAIL = os.environ.get("ATLASSIAN_EMAIL") or os.environ.get("CONFLUENCE_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN") or os.environ.get("CONFLUENCE_API_TOKEN")


def main() -> int:
    if not EMAIL or not TOKEN:
        print(
            "Set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN (or CONFLUENCE_* equivalents).",
            file=sys.stderr,
        )
        return 1

    md_path = ROOT / "docs" / "call-traces-scaling-tdd-confluence.md"
    markdown = md_path.read_text(encoding="utf-8")
    html_path = ROOT / ".confluence-update-payload-final.json"
    use_html = html_path.is_file()
    if use_html:
        payload = json.loads(html_path.read_text(encoding="utf-8"))
        body_value = payload["body"]["value"]
        body_format = payload["body"]["format"]
    else:
        body_value = markdown
        body_format = "markdown"

    auth = (EMAIL, TOKEN)
    get_url = f"{BASE}/wiki/rest/api/content/{PAGE_ID}?expand=version"
    r = requests.get(get_url, auth=auth, timeout=120)
    r.raise_for_status()
    current = r.json()
    version = int(current["version"]["number"]) + 1
    title = current["title"]

    if body_format == "html":
        storage = body_value
    else:
        storage = markdown

    update = {
        "version": {"number": version, "message": "v2.0 — E2E OTLP (S3 WAL, worker-traces, ClickHouse)"},
        "title": title,
        "type": "page",
        "body": {
            "storage": {
                "value": storage if body_format == "html" else f"<p>See markdown export — use MCP or storage conversion.</p>",
                "representation": "storage",
            }
        },
    }
    if body_format != "html":
        update["body"] = {
            "storage": {
                "value": f"<ac:structured-macro ac:name=\"markdown\"><ac:plain-text-body><![CDATA[{markdown}]]></ac:plain-text-body></ac:structured-macro>",
                "representation": "storage",
            }
        }

    put_url = f"{BASE}/wiki/rest/api/content/{PAGE_ID}"
    r2 = requests.put(put_url, auth=auth, json=update, timeout=180)
    if not r2.ok:
        print(r2.status_code, r2.text[:2000], file=sys.stderr)
        return 1
    print(f"Updated {title} → version {version}")
    print(f"{BASE}/wiki/spaces/ETD/pages/{PAGE_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
