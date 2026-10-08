# Smallest Atoms chat (eval production leg)

Text eval uses `wss://api.smallest.ai/atoms/v1/agent/connect?token=…&agent_id=…&mode=chat`:

1. Wait for `session.created`
2. Send `{"type":"input_text.send","text":"…"}`
3. Collect agent `transcript` events until the turn settles (see `smallest_atoms_chat.py`)

Voice **Talk** / playground uses `POST /conversation/webcall` + `atoms-client-sdk` (LiveKit audio) — not this path.

| File | Role |
|------|------|
| `app/services/agents/smallest_atoms_connect.py` | WebSocket URL + JSON frame parse |
| `app/services/agents/smallest_atoms_chat.py` | Session + turns |
| `app/services/agents/smallest_atoms_protocol.py` | Event helpers + fixture replay tests |
| `scripts/smallest_atoms_chat_probe.py` | Live debug |
