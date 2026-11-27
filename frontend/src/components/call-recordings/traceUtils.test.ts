import { describe, expect, it } from 'vitest'
import {
  buildSpanTranscriptMessages,
  isTurnIncomplete,
  parseUnixNano,
  sessionPipelineMode,
  resolveTraceStartNsFromSpans,
  turnToolCalls,
  unixNanoOffsetMs,
} from './traceUtils'

describe('parseUnixNano', () => {
  it('preserves large OTLP nanosecond timestamps via bigint math', () => {
    const traceStart = 1789153005157148232n
    const later = 1789153082946429429n
    expect(unixNanoOffsetMs(later, traceStart)).toBe(77789)
    expect(unixNanoOffsetMs(String(later), traceStart)).toBe(77789)
  })
})

describe('buildSpanTranscriptMessages', () => {
  it('includes every spoken TTS line instead of collapsing assistant text', () => {
    const traceStart = 1_000_000_000n
    const spans = [
      {
        span_id: 'tts-1',
        name: 'tts',
        start_time_unix_nano: traceStart + 100_000_000n,
        attributes: { text: 'Nice to meet you, Donna! Which products would you like to hear about?' },
      },
      {
        span_id: 'stt-1',
        name: 'stt',
        start_time_unix_nano: traceStart + 200_000_000n,
        attributes: { transcript: 'Donna Duke.' },
      },
      {
        span_id: 'tts-2',
        name: 'tts',
        start_time_unix_nano: traceStart + 300_000_000n,
        attributes: { text: 'Nice to meet you, Donna! Which of our three products would you like to explore?' },
      },
      {
        span_id: 'tts-3',
        name: 'tts',
        start_time_unix_nano: traceStart + 400_000_000n,
        attributes: { text: 'Goodbye, Donna! Take care!' },
      },
    ]
    const messages = buildSpanTranscriptMessages(spans, traceStart)
    expect(messages.map((m) => m.text)).toEqual([
      'Nice to meet you, Donna! Which products would you like to hear about?',
      'Donna Duke.',
      'Nice to meet you, Donna! Which of our three products would you like to explore?',
      'Goodbye, Donna! Take care!',
    ])
    expect(messages.map((m) => m.turn)).toEqual([1, 2, 2, 2])
  })
})

describe('resolveTraceStartNsFromSpans', () => {
  it('returns earliest span start', () => {
    const traceStart = resolveTraceStartNsFromSpans([
      {
        trace_id: 't',
        span_id: 'a',
        name: 'turn',
        start_time_unix_nano: 1789153082946429429,
      },
      {
        trace_id: 't',
        span_id: 'b',
        name: 'turn',
        start_time_unix_nano: 1789153005157148232,
      },
    ])
    expect(traceStart).toBe(parseUnixNano(1789153005157148232))
  })
})

describe('chat traces', () => {
  const start = 1_000_000_000n
  const spans = [
    { span_id: 't1', name: 'turn', start_time_unix_nano: start },
    {
      span_id: 'u1',
      parent_span_id: 't1',
      name: 'user_message',
      start_time_unix_nano: start + 1_000_000n,
      attributes: { 'gen_ai.operation.name': 'user_message', message: 'Where is my order?' },
    },
    {
      span_id: 'l1',
      parent_span_id: 't1',
      name: 'llm',
      start_time_unix_nano: start + 2_000_000n,
      attributes: { 'gen_ai.operation.name': 'chat', output: 'raw model text' },
    },
    {
      span_id: 'a1',
      parent_span_id: 't1',
      name: 'assistant_message',
      start_time_unix_nano: start + 9_000_000n,
      attributes: { 'gen_ai.operation.name': 'assistant_message', message: 'It ships tomorrow.' },
    },
    {
      span_id: 't2',
      name: 'turn',
      start_time_unix_nano: start + 20_000_000n,
    },
    {
      span_id: 'u2',
      parent_span_id: 't2',
      name: 'user_message',
      start_time_unix_nano: start + 21_000_000n,
      attributes: { 'gen_ai.operation.name': 'user_message', message: 'Thanks!' },
    },
    {
      span_id: 'l2',
      parent_span_id: 't2',
      name: 'llm',
      start_time_unix_nano: start + 22_000_000n,
      attributes: { 'gen_ai.operation.name': 'chat', output: 'You are welcome.' },
    },
  ]

  it('shows typed user messages and prefers the explicit reply over raw LLM output', () => {
    const messages = buildSpanTranscriptMessages(spans, start)
    expect(messages.map((m) => [m.role, m.text, m.turn])).toEqual([
      ['user', 'Where is my order?', 1],
      ['agent', 'It ships tomorrow.', 1],
      ['user', 'Thanks!', 2],
      ['agent', 'You are welcome.', 2],
    ])
  })

  it('reads tool calls stored on the turn and drops blank rows', () => {
    expect(
      turnToolCalls({
        tool_calls: [
          { name: 'lookup_order', latency_ms: 290 },
          { name: '  refund  ', latency_ms: Number.NaN, error: true },
          { name: '   ' },
          { name: 'search', latency_ms: null },
        ],
      }),
    ).toEqual([
      { name: 'lookup_order', latencyMs: 290, error: false },
      { name: 'refund', latencyMs: null, error: true },
      { name: 'search', latencyMs: null, error: false },
    ])
    expect(turnToolCalls(undefined)).toEqual([])
    expect(turnToolCalls({})).toEqual([])
  })

  it('does not flag chat turns as incomplete for missing STT/TTS', () => {
    const turns = [
      { turn_number: 1, sut_response_latency_ms: 900, llm_ttfb_ms: 210, extra: { pipeline_mode: 'chat' as const } },
      { turn_number: 2, sut_response_latency_ms: 500, extra: { pipeline_mode: 'chat' as const } },
    ]
    const mode = sessionPipelineMode(turns)
    expect(mode).toBe('chat')
    expect(isTurnIncomplete(turns[0], mode)).toBe(false)
    expect(isTurnIncomplete(turns[1], mode)).toBe(true)
  })
})
