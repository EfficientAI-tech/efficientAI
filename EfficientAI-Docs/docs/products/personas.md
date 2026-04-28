---
id: personas
title: Personas
sidebar_position: 2
---

# Personas

A Persona is the caller profile used to test your agent.

## Persona = profile + mapped voice

Each persona is explicitly mapped to a concrete voice identity:

- `tts_provider`
- `tts_voice_id`
- `tts_voice_name`
- `gender`

This keeps test behavior realistic and reproducible across repeated runs.

## Voice sources

Personas can use:

- built-in provider voices, or
- custom voices registered by your organization.

Custom voices appear in the same selection flow as built-in voices during persona creation and edits.

## Why this matters

Persona voice mapping enables:

- consistent replay of the same caller profile,
- cleaner comparison across model and prompt changes,
- easier debugging when quality shifts between runs.

## Persona fields

| Field | Description |
|---|---|
| `name` | Persona label used in tests. |
| `gender` | Persona gender metadata. |
| `tts_provider` | Voice provider used for synthesis. |
| `tts_voice_id` | Provider-specific voice identifier. |
| `tts_voice_name` | Human-readable voice name. |
| `is_custom` | Whether the selected voice is from custom catalog. |
