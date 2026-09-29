# Customer WebSocket chat (eval production leg)

Post-prod live chat agents with `chat_connection_type=customer_websocket` use one **persistent** `wss://` session per evaluator run.

## Turn contract

Each eval turn sends a single JSON text frame with the same body as the HTTP API integration (`customer_api_request_body`):

- `messages` — OpenAI-style roles from the transcript
- `agent_name`, `language`
- optional `transcript` when `include_full_transcript` is set in config

The production agent responds with one JSON (or plain text) frame. Reply text is extracted via the same rules as HTTP (`reply`, `message`, `content`, `text`, `response`, or OpenAI-style `choices`).

## Agent config (`chat_connection_config`)

| Key | Required | Description |
|-----|----------|-------------|
| `websocket_url` | yes | `wss://` or `ws://` endpoint |
| `websocket_auth_header` | no | Header name (default `Authorization`) |
| `websocket_auth_value` | no | Header value (stored encrypted) |

## Implementation

| Module | Role |
|--------|------|
| `app/services/agents/customer_websocket_chat.py` | Session + turns |
| `app/services/agents/chat_production_leg.py` | Production leg routing |
