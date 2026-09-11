import { describe, expect, it } from 'vitest'
import {
  formatInboundTtsMismatchMessage,
  formatTtsMismatchMessage,
  getSuiteTtsMismatchedPersonas,
  suiteHasTtsProviderMismatch,
} from './evaluatorTtsMismatch'

describe('evaluatorTtsMismatch', () => {
  const suite = {
    voice_bundle_tts_provider: 'voicemaker',
    personas: [
      { name: 'OpenAI Caller', tts_provider: 'openai' },
      { name: 'VoiceMaker Caller', tts_provider: 'voicemaker' },
    ],
  }

  it('detects stale personas', () => {
    expect(suiteHasTtsProviderMismatch(suite)).toBe(true)
    expect(getSuiteTtsMismatchedPersonas(suite)).toHaveLength(1)
    expect(getSuiteTtsMismatchedPersonas(suite)[0].name).toBe('OpenAI Caller')
  })

  it('formats outbound blocking copy', () => {
    const message = formatTtsMismatchMessage(suite)
    expect(message).toContain("voice bundle changed to 'voicemaker'")
    expect(message).toContain('Edit the evaluator')
  })

  it('formats inbound informational copy', () => {
    const message = formatInboundTtsMismatchMessage(suite)
    expect(message).toContain("voice bundle's default voice")
  })
})
