"""Trace a (simulated) custom voice agent into EfficientAI.

Runs three fake calls concurrently, each with a few turns, and prints their Call IDs.
Open Observability -> Calls in EfficientAI to see the transcripts and latencies.

    pip install "efficientai-sdk[otel]"
    export EFFICIENTAI_BASE_URL=http://localhost:8000
    export EFFICIENTAI_API_KEY=...
    export EFFICIENTAI_WORKSPACE_ID=...
    python examples/custom_agent_tracing.py

Replace the fake_* functions with your real STT, LLM and TTS calls.
"""

from __future__ import annotations

import asyncio
import logging
import random

from efficientai_sdk import AsyncEfficientAI

SCRIPTS = [
    [
        ("Hi, I'd like to book a table for tonight", "Sure! How many people?"),
        ("Four of us, around eight", "Booked: four people at 8pm. Anything else?"),
        ("No, that's all, thanks", "Enjoy your dinner!"),
    ],
    [
        (
            "My internet keeps dropping every evening",
            "Sorry to hear that. Have you restarted the router?",
        ),
        ("Yes, twice today", "Thanks. I'll schedule a technician visit for tomorrow."),
    ],
    [
        ("What's my account balance?", "Your balance is $42.10."),
        ("When is the next payment due?", "Your next payment is due on the 15th."),
    ],
]


async def fake_stt(text: str) -> str:
    await asyncio.sleep(random.uniform(0.15, 0.3))
    return text


async def fake_llm(reply: str) -> tuple[str, float]:
    first_token = random.uniform(0.2, 0.5)
    await asyncio.sleep(first_token + 0.2)
    return reply, first_token


async def fake_tts(text: str) -> float:
    first_byte = random.uniform(0.08, 0.2)
    await asyncio.sleep(first_byte + 0.3)
    return first_byte


async def run_call(client: AsyncEfficientAI, script: list[tuple[str, str]]) -> str:
    async with client.trace.session(transport="websocket") as call:
        for user_says, agent_says in script:
            with call.turn():
                with call.stt(model="nova-3", provider="deepgram") as stt:
                    stt.set_transcript(await fake_stt(user_says))
                with call.llm(model="gpt-4o", provider="openai") as llm:
                    reply, ttfb = await fake_llm(agent_says)
                    llm.set_output(reply).set_ttfb(ttfb)
                with call.tts(model="sonic", provider="cartesia") as tts:
                    tts.set_text(reply).set_ttfb(await fake_tts(reply))
        return call.call_short_id or "(tracing disabled, see warnings above)"


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with AsyncEfficientAI() as client:
        await client.verify()
        call_ids = await asyncio.gather(*(run_call(client, script) for script in SCRIPTS))
    for call_id in call_ids:
        print(f"Traced call {call_id}")


if __name__ == "__main__":
    asyncio.run(main())
