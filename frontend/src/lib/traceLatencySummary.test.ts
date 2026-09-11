import { describe, expect, it } from 'vitest'
import {
  computeResponseLatencySummary,
  responseLatencySampleLabel,
  responseLatencySamples,
} from './traceLatencySummary'

describe('traceLatencySummary', () => {
  it('includes user turns and measured greeting openers', () => {
    const turns = [
      { sut_response_latency_ms: 800, extra: { sut_measured_e2e: true, assistant_text: 'Hi' } },
      { sut_response_latency_ms: 1200, extra: { user_text: 'hello' } },
      { sut_response_latency_ms: 2400, extra: { user_text: 'bye' } },
    ]
    expect(responseLatencySamples(turns)).toEqual([800, 1200, 2400])
    const summary = computeResponseLatencySummary(turns)
    expect(summary?.p50).toBe(1200)
  })

  it('excludes agent-only openers with llm fallback sut', () => {
    const turns = [
      { sut_response_latency_ms: 9000, llm_ttfb_ms: 9000, extra: { assistant_text: 'Welcome' } },
      { sut_response_latency_ms: 1200, extra: { user_text: 'hello' } },
      { sut_response_latency_ms: 2400, extra: { user_text: 'bye' } },
    ]
    expect(responseLatencySamples(turns)).toEqual([1200, 2400])
    expect(computeResponseLatencySummary(turns)?.p50).toBe(1200)
  })

  it('excludes user turns with llm-only partial fallback', () => {
    const turns = [
      {
        sut_response_latency_ms: 400,
        llm_ttfb_ms: 400,
        extra: { user_text: 'hi', sut_is_partial_fallback: true },
      },
      { sut_response_latency_ms: 1200, extra: { user_text: 'bye' } },
    ]
    expect(responseLatencySamples(turns)).toEqual([1200])
  })

  it('labels sample count vs total turns', () => {
    expect(responseLatencySampleLabel(7, 8)).toBe('7 of 8 turns')
    expect(responseLatencySampleLabel(8, 8)).toBe('8 turns')
  })

  it('matches TDD nearest-rank percentiles', () => {
    const turns = [
      { sut_response_latency_ms: 800, extra: { sut_measured_e2e: true } },
      { sut_response_latency_ms: 920, extra: { user_text: 'a' } },
      { sut_response_latency_ms: 1100, extra: { user_text: 'b' } },
      { sut_response_latency_ms: 1400, extra: { user_text: 'c' } },
    ]
    const summary = computeResponseLatencySummary(turns)
    expect(summary?.p50).toBe(1100)
    expect(summary?.p90).toBe(1400)
    expect(summary?.p95).toBe(1400)
  })
})
