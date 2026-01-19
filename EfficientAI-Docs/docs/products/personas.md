---
id: personas
title: Personas
sidebar_position: 2
---

# Personas

## What is a Persona?

A **Persona** is a simulated character. It's the "Actor" that calls your AI.

When you test your Voice AI, you don't want every test call to sound the same. A real customer base is diverse—some speak fast, some possess strong accents, and some call from noisy cafes.

With Personas, you can create characters like:
*   **"John"**: Speaks English with a standard American accent, calling from a quiet office.
*   **"Maria"**: Speaks Spanish, calling from a noisy street.
*   **"Raj"**: Speaks English with an Indian accent.

By testing with different Personas, you ensure your AI works for *everyone*, not just people with perfect studio microphones.

---

## Technical Details

Personas represent the simulated users that interact with your Voice AI agents. They are configured with specific demographic and environmental characteristics to test how well your agent handles variety in speech patterns, accents, and acoustic environments.

### Configuration

A Persona is defined by the following attributes:

| Attribute | Type | Description |
|---|---|---|
| `name` | String | A friendly name for the persona (e.g., "John Doe - American Male"). |
| `language` | Enum | The primary language spoken by the persona. |
| `accent` | Enum | The specific accent of the persona, used to test speech recognition robustness. |
| `gender` | Enum | The gender of the voice (Male, Female, Neutral). |
| `background_noise` | Enum | Simulated environmental noise added to the audio stream. |

### Attribute Definitions

#### Languages
Supported languages: `en` (English), `es` (Spanish), `fr` (French), `de` (German), `zh` (Chinese), `ja` (Japanese), `hi` (Hindi), `ar` (Arabic).

#### Accents
Accents determine the prosody and pronunciation nuances of the Text-to-Speech (TTS) voice used: `american`, `british`, `australian`, `indian`, `chinese`, `spanish`, `french`, `german`, `neutral`.

#### Background Noise
To simulate real-world conditions, varied acoustic environments can be applied:
- `none`: Clean studio audio.
- `office`: Typical office ambience.
- `street`: Outdoor urban environment.
- `cafe`: Coffee shop environment.
- `home`: Indoor residential environment.
- `call_center`: Busy call center background.
