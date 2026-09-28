export function isChatMedium(medium?: string | null): boolean {
  return (medium || '').toLowerCase() === 'chat'
}

export type AgentMediumFilter = 'voice' | 'chat'

export function filterAgentsByMedium<T extends { call_medium?: string | null }>(
  agents: T[],
  filter: AgentMediumFilter,
): T[] {
  return agents.filter((agent) =>
    filter === 'chat' ? isChatMedium(agent.call_medium) : !isChatMedium(agent.call_medium),
  )
}

export function formatAgentMediumLabel(medium?: string | null, callType?: string | null): string {
  const m = (medium || 'phone_call').toLowerCase()
  if (m === 'chat') return 'Text chat (LLM)'
  if (m === 'web_call') return 'Web voice'
  if (callType === 'inbound') return 'Phone inbound'
  return 'Phone outbound'
}

export function isLlmToLlmSimulationResult(
  callData?: { simulation?: string; source?: string } | null,
): boolean {
  if (!callData || typeof callData !== 'object') return false
  return (
    callData.simulation === 'llm_to_llm' || callData.source === 'llm_to_llm_simulation'
  )
}

/** Text chat agent runs and chat-modality sim transcripts (not voice-bundle LLM sim). */
export function isChatEvalResult(input: {
  agent?: { call_medium?: string | null } | null
  call_data?: { modality?: string; simulation?: string; source?: string } | null
}): boolean {
  if (isChatMedium(input.agent?.call_medium)) return true
  const cd = input.call_data
  if (!cd || typeof cd !== 'object') return false
  return cd.modality === 'chat'
}

/** Transcript-first eval (no live phone/WebRTC recording). */
export function isTranscriptOnlyEvalResult(input: {
  agent?: { call_medium?: string | null } | null
  call_data?: { modality?: string; simulation?: string; source?: string } | null
}): boolean {
  return isChatEvalResult(input) || isLlmToLlmSimulationResult(input.call_data)
}
