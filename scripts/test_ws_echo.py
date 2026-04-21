"""
Minimal WebSocket echo server for testing the Generic WebSocket voice client.

Usage:
    pip install websockets
    python scripts/test_ws_echo.py

Then connect from the Custom WebSocket tab using:
    ws://localhost:8766

The server:
  - Buffers incoming audio frames for ECHO_DELAY_S seconds, then replays them
  - Sends periodic fake agent transcript messages
  - Logs activity to the console
"""

import asyncio
import json
import sys
import time

import websockets

sys.stdout.reconfigure(line_buffering=True)

PORT = 9876
ECHO_DELAY_S = 3.0
GREETING_DELAY_S = 2.0
FRAME_INTERVAL_S = 0.1  # matches the generic protocol's 100ms sendIntervalMs

GREETING_TEXT = "Hello! I'm the echo bot. Whatever you say, I'll repeat back after a 3-second delay."


async def echo_worker(queue: asyncio.Queue, ws):
    """Drains the queue and replays audio frames with original timing."""
    while True:
        frame_b64, scheduled_time = await queue.get()
        now = time.time()
        wait = scheduled_time - now
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await ws.send(json.dumps({"audio": frame_b64}))
        except websockets.exceptions.ConnectionClosed:
            break


async def handler(ws):
    remote = ws.remote_address
    print(f"[+] Client connected from {remote}")

    echo_queue: asyncio.Queue = asyncio.Queue()
    worker_task = asyncio.create_task(echo_worker(echo_queue, ws))

    audio_count = 0
    start = time.time()
    greeting_sent = False

    try:
        async for raw in ws:
            elapsed = time.time() - start

            if not greeting_sent and elapsed > GREETING_DELAY_S:
                greeting_sent = True
                await ws.send(json.dumps({
                    "type": "transcript",
                    "role": "agent",
                    "content": GREETING_TEXT,
                }))
                print(f"    [transcript] Sent greeting")

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                print(f"    [?] Non-JSON message ({len(raw)} bytes)")
                continue

            audio_b64 = msg.get("audio")
            if audio_b64 and isinstance(audio_b64, str) and len(audio_b64) > 20:
                audio_count += 1
                if audio_count % 50 == 1:
                    print(f"    [audio] Received frame #{audio_count} ({len(audio_b64)} b64 chars)")

                echo_queue.put_nowait((audio_b64, time.time() + ECHO_DELAY_S))

                if audio_count % 200 == 0:
                    await ws.send(json.dumps({
                        "type": "transcript",
                        "role": "user",
                        "content": f"(echo test — {audio_count} audio frames received)",
                    }))
                    await ws.send(json.dumps({
                        "type": "transcript",
                        "role": "agent",
                        "content": f"I've echoed back {audio_count} audio frames so far!",
                    }))
            else:
                print(f"    [msg] {json.dumps(msg)[:200]}")

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[-] Client {remote} disconnected: {e.code} {e.reason}")
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        worker_task.cancel()
        print(f"[-] Session ended — {audio_count} audio frames received in {time.time() - start:.1f}s")


async def main():
    print(f"Echo WebSocket server starting on ws://localhost:{PORT}")
    print(f"Connect from the Custom WebSocket tab with: ws://localhost:{PORT}")
    print()
    async with websockets.serve(handler, "0.0.0.0", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
