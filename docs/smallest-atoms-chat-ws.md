# Smallest Atoms chat WebSocket (eval production leg)

Backend chat eval uses the same **LiveKit data channel** as `atoms-client-sdk` text/chat mode:
`POST /conversation/register-call` with `mode: chat` (or `/conversation/chat`) → `host` + JWT →
`room.connect(host, token)` → publish user `transcript` / `topic: user_response` → receive agent `transcript` + `agent_stop_talking`.

## Code map

| Piece | Role |
|-------|------|
| `app/services/agents/smallest_atoms_protocol.py` | **Protocol**: classify events, extract assistant text, accumulate a turn. No I/O. |
| `app/services/agents/smallest_atoms_connect.py` | **Session**: register-call / chat API → LiveKit host + token. |
| `app/services/agents/smallest_atoms_chat.py` | **Transport**: LiveKit room, data packets, retries on write conflict. |
| `tests/fixtures/smallest_atoms_chat/*.json` | Golden inbound transcripts replayed in unit tests. |
| `scripts/smallest_atoms_chat_probe.py` | Live probe: log classified events against a real agent. |

## Outbound (client → room data channel)

```json
{"type": "transcript", "text": "<user message>", "topic": "user_response", "timestamp": 0}
```

## Inbound (documented in protocol module)

- **Session meta**: `session.created`, `session.started`, … — optional; do not block send on these alone.
- **Assistant text**: `transcript` (role assistant/agent/ai), `agent_response`, …
- **Turn complete**: `agent_stop_talking`, `session.closed`, …
- **Errors**: `type: error` — write conflict → retry once with a fresh socket.

## Extending the protocol

1. Run `python scripts/smallest_atoms_chat_probe.py --agent-id ...` (set `SMALLEST_API_KEY`).
2. Save interesting sessions to `tests/fixtures/smallest_atoms_chat/<name>.json` (array of events).
3. Add types to `SESSION_META_TYPES` / `TURN_COMPLETE_TYPES` or teach `extract_assistant_text()` in `smallest_atoms_protocol.py`.
4. Run `pytest tests/test_services/test_smallest_atoms_protocol.py`.

## Turn timing

- **Per-turn budget** (`AtomsChatTimeouts.turn_seconds`, default 90s): entire user message → assistant reply.
- **Recv slices** (5s): avoid one blocking `recv` consuming the full budget without sending.
- **First turn on a socket**: send user text after the first inbound event or after a recv timeout (matches observed server behavior).

## Simulation errors

Production leg failures are wrapped as `ProductionChatLegError` in `llm_to_llm_evaluator_simulation.py` so worker logs distinguish platform chat from test-agent LLM failures.
