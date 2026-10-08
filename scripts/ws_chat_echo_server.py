#!/usr/bin/env python3
"""Minimal WebSocket server for testing customer_websocket chat agents."""

import asyncio
import json

import websockets


async def handler(ws):
    async for raw in ws:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("messages"):
                last = data["messages"][-1]
                user = last.get("content", "ok") if isinstance(last, dict) else "ok"
            else:
                user = str(data)
            text = f"Echo: {user}"
        except (json.JSONDecodeError, TypeError, KeyError, IndexError):
            text = f"Echo: {raw!s}"
        await ws.send(json.dumps({"reply": text}))


async def main():
    port = 8765
    async with websockets.serve(handler, "0.0.0.0", port):
        print(f"WebSocket echo on ws://0.0.0.0:{port}  (use ws://localhost:{port} in agent config)")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
