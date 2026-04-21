---
id: prompt-optimization
title: Prompt Optimization
sidebar_position: 7
---

# Prompt Optimization

Prompt Optimization is an enterprise feature for iteratively improving agent prompts using evaluation feedback.

## What gets optimized

Each run starts from a seed prompt:

- provider prompt, if available, otherwise
- internal agent description.

The optimizer generates candidate prompts, evaluates them against available examples and enabled metrics, and ranks them by score.

## Run configuration

Common run controls include:

- `max_metric_calls` for evaluation budget
- `minibatch_size` for examples per iteration

These settings determine optimization depth, runtime, and cost.

## Candidate workflow

For each optimization run:

1. Review generated candidates and their scores.
2. Compare candidate prompt text against the seed prompt.
3. **Accept** the candidate you want to promote.
4. Optionally **Push to Provider** to update the linked external agent prompt.

## Push behavior

When a candidate is pushed:

- EfficientAI updates the prompt in the external provider,
- updates local agent prompt fields,
- records push timing for traceability.

## Best practices

- Use representative completed evaluator results as optimization data.
- Keep enabled metric sets stable while comparing candidates.
- Review prompt semantics in addition to score before pushing.
