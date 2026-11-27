import { describe, expect, it } from 'vitest'
import { traceListModality, traceListPlatformSummary, traceTransportDisplayLabel } from './traceListLabels'

describe('traceListLabels', () => {
  it('defaults custom transport to voice until session_modality is known', () => {
    expect(traceListModality(null, 'custom')).toBe('voice')
    expect(traceListPlatformSummary(null, 'custom')).toEqual({
      modality: 'voice',
      detail: 'HTTP API',
    })
  })

  it('uses session_modality when present', () => {
    expect(traceListModality('chat', 'webrtc')).toBe('chat')
    expect(traceListModality('voice', 'custom')).toBe('voice')
  })

  it('maps known transports', () => {
    expect(traceTransportDisplayLabel('websocket')).toBe('WebSocket')
    expect(traceTransportDisplayLabel('phone')).toBe('Phone')
  })
})