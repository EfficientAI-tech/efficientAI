import { describe, expect, it } from 'vitest'
import {
  hasCallRecordingDetails,
  hasEnrichedCallRecordingDetails,
  hasRecordingUrlInCallData,
  hasTranscriptInCallData,
} from './callRecordingDetails'

describe('hasEnrichedCallRecordingDetails', () => {
  it('returns false for token-only in-progress payloads', () => {
    expect(
      hasEnrichedCallRecordingDetails({
        status: 'updated',
        call_data: { assistantOverrides: { variableValues: { token: 'abc' } } },
      }),
    ).toBe(false)
  })

  it('returns false for ended stub without transcript or recording URL', () => {
    expect(
      hasEnrichedCallRecordingDetails({
        status: 'ended',
        call_data: {
          status: 'ended',
          endedAt: '2026-01-01T00:00:00Z',
          durationMs: 12000,
        },
      }),
    ).toBe(false)
  })

  it('returns true when transcript is present', () => {
    expect(
      hasEnrichedCallRecordingDetails({
        call_data: { transcript: 'hello world' },
      }),
    ).toBe(true)
  })

  it('returns true when recording URL is present', () => {
    expect(
      hasEnrichedCallRecordingDetails({
        call_data: { recordingUrl: 'https://example.com/audio.wav' },
      }),
    ).toBe(true)
  })
})

describe('hasCallRecordingDetails', () => {
  it('returns true for ended stub with substantive payload', () => {
    expect(
      hasCallRecordingDetails({
        status: 'ended',
        call_data: {
          status: 'ended',
          endedAt: '2026-01-01T00:00:00Z',
          durationMs: 12000,
        },
      }),
    ).toBe(true)
  })
})

describe('call data helpers', () => {
  it('detects transcript and recording fields independently', () => {
    expect(hasTranscriptInCallData({ messages: [{ role: 'user', content: 'hi' }] })).toBe(true)
    expect(hasRecordingUrlInCallData({ recording_url: 'https://x.test/a.wav' })).toBe(true)
  })
})
