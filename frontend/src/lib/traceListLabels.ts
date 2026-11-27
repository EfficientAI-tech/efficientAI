/** Human labels for OTLP trace rows on Observability → Calls (not telephony webhooks). */

export type TraceListModality = 'chat' | 'voice'

const TRANSPORT_LABELS: Record<string, string> = {
  custom: 'HTTP API',
  websocket: 'WebSocket',
  webrtc: 'Web call',
  phone: 'Phone',
}

export function traceListModality(
  sessionModality?: 'chat' | 'voice' | null,
  transport?: string | null,
): TraceListModality {
  if (sessionModality === 'chat') return 'chat'
  if (sessionModality === 'voice') return 'voice'
  const t = (transport ?? '').toLowerCase()
  if (t === 'phone' || t === 'webrtc' || t === 'sip') return 'voice'
  if (t === 'websocket') return 'voice'
  if (t === 'custom') return 'voice'
  return 'voice'
}

export function traceTransportDisplayLabel(transport?: string | null): string | null {
  if (!transport) return null
  const key = transport.toLowerCase()
  return TRANSPORT_LABELS[key] ?? transport.replace(/_/g, ' ')
}

export function traceListPlatformSummary(
  sessionModality?: 'chat' | 'voice' | null,
  transport?: string | null,
): { modality: TraceListModality; detail: string | null } {
  const modality = traceListModality(sessionModality, transport)
  const transportLabel = traceTransportDisplayLabel(transport)
  if (modality === 'chat') {
    return { modality, detail: transportLabel }
  }
  return { modality, detail: transportLabel }
}