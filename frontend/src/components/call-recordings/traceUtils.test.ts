import { describe, expect, it } from 'vitest'
import {
  buildSpanTranscriptMessages,
  parseUnixNano,
  resolveTraceStartNsFromSpans,
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
