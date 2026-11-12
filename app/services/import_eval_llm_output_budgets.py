"""Shared LLM output token budgets for import-eval analysis jobs."""

# Two-step pattern: first call, then one retry at double if truncated or JSON invalid.
IMPORT_EVAL_LLM_OUTPUT_FIRST = 32_768
IMPORT_EVAL_LLM_OUTPUT_RETRY = 65_536

# Diariser for Gemini 3.x and GLM: smaller pair (see llm_diarisation).
DIARISER_COMPACT_OUTPUT_FIRST = 8_192
DIARISER_COMPACT_OUTPUT_RETRY = 16_384
