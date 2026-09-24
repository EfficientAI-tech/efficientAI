# LLM chat evals — simple diagrams (paste into Excalidraw → Mermaid)

## WHY

```mermaid
flowchart LR
  User["Real customer"]
  Bot["Chat bot"]
  Bad["Wrong answer"]
  Pain["Lost trust money"]

  User --> Bot
  Bot --> Bad
  Bad --> Pain
```

Pre-prod testing tries to catch `Bad` before `User` sees it.

## WHAT

```mermaid
flowchart LR
  Main["Your bot Main agent\nproduction prompt"]
  Test["Fake customer\npersona scenario"]
  Save["Transcript + grades"]

  Test <-->|"text chat"| Main
  Main --> Save
  Test --> Save
```

## Three layers (connection → agent → eval)

```mermaid
flowchart TB
  L1["Layer 1 Identity\nprompt name language"]
  L2["Layer 2 Connection\nhow we reach the bot"]
  L3["Layer 3 Tests\npersona scenario metrics"]

  L1 --> L2 --> L3 --> Run["Run simulation"]
```

## Your 5 steps

```mermaid
flowchart TB
  S1["Create chat agent"]
  S2["Connection LLMs"]
  S3["Persona scenario"]
  S4["Run suite"]
  S5["Read scores"]

  S1 --> S2 --> S3 --> S4 --> S5
```

## Tech on Run

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Worker
  participant LLMs as Two LLMs
  participant Metrics

  UI->>API: Run
  API->>Worker: Task
  loop Turns
    Worker->>LLMs: Main and test messages
  end
  Worker->>Metrics: Score transcript
  Metrics->>UI: Results
```
