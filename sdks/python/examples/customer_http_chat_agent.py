#!/usr/bin/env python3
"""Minimal HTTP customer chat agent for EFF-111 local simulation testing.

    export EFFICIENTAI_BASE_URL=http://localhost:8000
    export EFFICIENTAI_API_KEY=...
    export EFFICIENTAI_WORKSPACE_ID=...
    uv run python examples/customer_http_chat_agent.py

Point a chat agent (HTTP API) at http://localhost:9000 with path /chat, then run a suite.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("MOCK_HTTP_CHAT_PORT", "9000"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw.decode("utf-8"))
        call_short = self.headers.get("X-EfficientAI-Call-Short-Id", "")
        run_id = self.headers.get("X-EfficientAI-Run-Id", "")
        print(f"POST {self.path} call_short_id={call_short!r} run_id={run_id!r}")

        messages = body.get("messages") or []
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = (msg.get("content") or "").strip()
                break
        reply = f"Mock reply to: {last_user[:120]}" if last_user else "Hello from mock HTTP agent"

        headers = {k: v for k, v in self.headers.items()}
        try:
            from efficientai_sdk import EfficientAI

            with EfficientAI() as client, client.trace.from_request(
                headers, channel="chat"
            ) as call, call.turn():
                call.user_message(last_user or "(empty)")
                with call.llm(model="mock", provider="local") as llm:
                    llm.set_output(reply).set_ttfb(0.05)
        except Exception as exc:
            print(f"tracing skipped: {exc}")

        payload = json.dumps({"reply": reply}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = HTTPServer(("localhost", PORT), Handler)
    print(f"Customer HTTP chat mock listening on http://localhost:{PORT}/chat")
    server.serve_forever()


if __name__ == "__main__":
    main()
