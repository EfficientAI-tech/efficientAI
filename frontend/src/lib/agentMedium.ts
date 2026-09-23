export function isChatMedium(medium?: string | null): boolean {
  return (medium || '').toLowerCase() === 'chat'
}

export function formatAgentMediumLabel(medium?: string | null, callType?: string | null): string {
  const m = (medium || 'phone_call').toLowerCase()
  if (m === 'chat') return 'Text chat (LLM)'
  if (m === 'web_call') return 'Web voice'
  if (callType === 'inbound') return 'Phone inbound'
  return 'Phone outbound'
}

export function isChatEvalResult(input: {
  agent?: { call_medium?: string | null } | null
  call_data?: { modality?: string; simulation?: string; source?: string } | null
}): boolean {
  if (isChatMedium(input.agent?.call_medium)) return true
  const cd = input.call_data
  if (!cd || typeof cd !== 'object') return false
  if (cd.modality === 'chat') return true
  if (cd.simulation === 'llm_to_llm' || cd.source === 'llm_to_llm_simulation') return true
  return false
}
