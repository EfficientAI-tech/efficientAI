import { describe, expect, it } from 'vitest'
import { buildOtelCallTimeline, buildVapiCallTimeline } from './callTimelineUtils'

describe('buildVapiCallTimeline', () => {
  it('orders call ended after pipeline events and uses real timestamps', () => {
    const events = buildVapiCallTimeline({
      status: 'ended',
      type: 'webCall',
      createdAt: '2026-09-02T18:24:30.000Z',
      startedAt: '2026-09-02T18:24:31.000Z',
      endedAt: '2026-09-02T18:25:03.000Z',
      endedReason: 'customer-ended-call',
      artifact: {
        messages: [
          { role: 'system', message: 'System prompt', secondsFromStart: 0 },
          { role: 'bot', message: 'Hello.', secondsFromStart: 1.62 },
          { role: 'user', message: 'Hi', secondsFromStart: 8.46, duration: 1200 },
        ],
        performanceMetrics: {
          turnLatencies: [
            {
              turnNumber: 1,
              transcriberLatency: 571,
              endpointingLatency: 304,
              modelLatency: 359,
              voiceLatency: 350,
              turnLatency: 1287,
            },
            {
              turnNumber: 2,
              transcriberLatency: 516,
              endpointingLatency: 300,
              modelLatency: 509,
              voiceLatency: 354,
              turnLatency: 1397,
            },
          ],
        },
      },
    })

    const endedIdx = events.findIndex((e) => e.title === 'Call ended')
    const lastPipelineIdx = events.map((e) => e.title).lastIndexOf('Turn 2 pipeline complete')
    expect(endedIdx).toBeGreaterThan(lastPipelineIdx)

    const ended = events[endedIdx]
    expect(ended.offsetMs).toBeGreaterThanOrEqual(32000)

    expect(events.some((e) => e.title === 'Turn 1 — transcriber')).toBe(true)
    expect(events.some((e) => e.detail?.includes('$'))).toBe(false)
    expect(events.some((e) => e.detail?.startsWith('https://'))).toBe(false)
  })

  it('ignores null entries in artifact messages', () => {
    const events = buildVapiCallTimeline({
      status: 'ended',
      startedAt: '2026-09-02T18:24:31.000Z',
      endedAt: '2026-09-02T18:25:03.000Z',
      artifact: {
        messages: [
          null,
          { role: 'user', message: 'Hi', secondsFromStart: 1 },
          { role: 'bot', message: 'Hello', secondsFromStart: 2 },
        ],
      },
    })

    expect(events.some((e) => e.title === 'User spoke')).toBe(true)
    expect(events.some((e) => e.title === 'Call ended')).toBe(true)
  })
})

describe('buildOtelCallTimeline', () => {
  const traceStart = 1_000_000_000_000

  it('orders user message before STT and agent message after TTS within a turn', () => {
    const spans = [
      {
        span_id: 'conv',
        name: 'conversation',
        start_time_unix_nano: traceStart,
        end_time_unix_nano: traceStart + 40_000_000_000,
      },
      {
        span_id: 't1',
        parent_span_id: 'conv',
        name: 'turn',
        start_time_unix_nano: traceStart,
        end_time_unix_nano: traceStart + 9_000_000_000,
        attributes: { 'turn.number': 1 },
      },
      {
        span_id: 'llm1',
        parent_span_id: 't1',
        name: 'llm',
        start_time_unix_nano: traceStart + 650_000_000,
        end_time_unix_nano: traceStart + 3_400_000_000,
        attributes: { 'turn.number': 1, 'gen_ai.operation.name': 'llm' },
      },
      {
        span_id: 'tts1',
        parent_span_id: 't1',
        name: 'tts',
        start_time_unix_nano: traceStart + 3_250_000_000,
        end_time_unix_nano: traceStart + 3_260_000_000,
        attributes: { 'turn.number': 1, 'gen_ai.operation.name': 'tts' },
      },
      {
        span_id: 't2',
        parent_span_id: 'conv',
        name: 'turn',
        start_time_unix_nano: traceStart + 9_730_000_000,
        end_time_unix_nano: traceStart + 21_390_000_000,
        attributes: { 'turn.number': 2 },
      },
      {
        span_id: 'stt2',
        parent_span_id: 't2',
        name: 'stt',
        start_time_unix_nano: traceStart + 11_800_000_000,
        end_time_unix_nano: traceStart + 11_810_000_000,
        attributes: {
          'turn.number': 2,
          'gen_ai.operation.name': 'stt',
          transcript: 'Hi Alex, how are you?',
        },
      },
      {
        span_id: 'llm2',
        parent_span_id: 't2',
        name: 'llm',
        start_time_unix_nano: traceStart + 12_300_000_000,
        end_time_unix_nano: traceStart + 15_000_000_000,
        attributes: { 'turn.number': 2, 'gen_ai.operation.name': 'llm' },
      },
      {
        span_id: 'tts2',
        parent_span_id: 't2',
        name: 'tts',
        start_time_unix_nano: traceStart + 14_860_000_000,
        end_time_unix_nano: traceStart + 14_920_000_000,
        attributes: { 'turn.number': 2, 'gen_ai.operation.name': 'tts' },
      },
    ]

    const events = buildOtelCallTimeline(spans, [
      {
        turn_number: 1,
        extra: { assistant_text: 'Good morning! This is Alex speaking.' },
      },
      {
        turn_number: 2,
        extra: {
          user_text: 'Hi Alex, how are you?',
          assistant_text: "I'm doing well, thank you for asking!",
        },
      },
    ])

    const userIdx = events.findIndex((e) => e.title === 'User spoke (turn 2)')
    const sttIdx = events.findIndex((e) => e.category === 'stt' && e.detail?.includes('Hi Alex'))
    const llmIdx = events.findIndex(
      (e) => e.category === 'llm' && e.offsetMs >= 12_000 && e.offsetMs <= 13_000,
    )
    const agentIdx = events.findIndex((e) => e.title === 'Agent spoke (turn 2)')

    expect(userIdx).toBeGreaterThan(-1)
    expect(sttIdx).toBeGreaterThan(userIdx)
    expect(llmIdx).toBeGreaterThan(sttIdx)
    expect(agentIdx).toBeGreaterThan(llmIdx)
    expect(events[userIdx].offsetMs).toBeLessThanOrEqual(events[sttIdx].offsetMs)
  })
})
