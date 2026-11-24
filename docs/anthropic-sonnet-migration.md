# Anthropic Sonnet default migration

`AnthropicLLMService` now defaults to `claude-sonnet-5-5`. Anthropic retires
`claude-sonnet-4-5-20250929` and its `claude-sonnet-4-5` alias on November 30, 2026.
See the [retirement notice](https://platform.claude.com/docs/en/about-claude/model-deprecations)
and [migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide).

Upgrade dependencies with `pip install -e .` to install `anthropic>=1.9.0`.
Explicit model selections are preserved. Update saved settings that select Sonnet 4.5
before retirement; changing the constructor default does not migrate saved configurations.
Other Anthropic model selections keep their sampling settings.

For Sonnet 5.5, the service removes `temperature`, `top_p`, and `top_k`, including
values supplied through `InputParams.extra` or its `extra_body`. Effort defaults
explicitly to `high`; streaming requests can override it using
`InputParams(extra={"output_config": {"effort": "medium"}})`.

Thinking is adaptive by default, and `max_tokens` covers both thinking and text.
Streaming keeps the configured token limit (4096 by default); one-shot inference
keeps its existing 8192-token limit. Revisit these budgets for your workload.
To avoid up-front thinking in streaming requests, use
`InputParams(extra={"thinking": {"type": "between_tools"}})` with effort at most `high`.
Legacy `enabled`/`disabled` thinking settings, thinking budgets, forced `any`/`tool`
choices, and assistant prefills need explicit migration. The service reports an
error before sending those unsupported requests.

Completed Sonnet 5.5 streaming responses are stored verbatim in the shared context
before tools execute. This preserves empty signed thinking, redacted blocks, text
whitespace, and every tool call. Both universal `LLMContext` and legacy
`AnthropicLLMContext` aggregators avoid adding duplicate text or tool declarations.
Interrupted or incomplete streams do not store partial signed responses. A response
that completed generation remains in history even if speech playback is interrupted
later, because subsequent thinking signatures depend on that exact history.

The default ID targets the direct Claude API. Custom Bedrock and Vertex clients
still require the caller to select their platform's model ID. The documented
Bedrock ID `anthropic.claude-sonnet-5-5` (including regional inference profile prefixes)
receives the same request filtering and context preservation. See
[platform model IDs](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).
