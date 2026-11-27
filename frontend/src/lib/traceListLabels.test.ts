import { describe, expect, it } from 'vitest'
import { traceListModality, traceListPlatformSummary, traceTransportDisplayLabel } from './traceListLabels'

describe('traceListLabels', () => {
  it('treats customer HTTP sim traces as chat', () => {
    expect(traceListModality(null, 'custom')).toBe('chat')
    expect(traceListPlatformSummary(null, 'custom')).toEqual({
      modality: 'chat',
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