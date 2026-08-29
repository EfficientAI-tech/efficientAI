# Span Contract (V1)

This contract is optimized for EfficientAI call-trace UI rendering.

## Required hierarchy

```text
conversation
└── turn
    ├── stt
    ├── llm
    └── tts
```

`turn` spans are optional in the frontend rendering path, but are strongly preferred.

## Stable span names

- `conversation` (root)
- `turn`
- `stt`
- `llm`
- `tts`

Phase 2:

- `s2s`
- `tool_call`

## Required attributes

### `conversation`

- `conversation.id`
- `organization_id`
- `workspace_id`
- `agent_id`

### `turn`

- `turn.number`

### `stt`

- `stt.provider`
- `stt.transcript` (subject to transcript policy)
- `gen_ai.request.model` (when available)

### `llm`

- `gen_ai.system`
- `gen_ai.request.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`

### `tts`

- `tts.provider`
- `tts.characters`
- `gen_ai.request.model` (when available)

## Notes

- Do not add spans for internal non-service transforms.
- Keep names stable; UI styling and rollups depend on this.
- If an existing attribute key already exists under a different legacy name, dual-write both keys during migration windows.
