export type PersonaMediumFilter = 'voice' | 'chat'

export type PersonaSimulationMedium = 'voice' | 'text'

export function personaSimulationMedium(persona: {
  simulation_medium?: string | null
  tts_provider?: string | null
}): PersonaSimulationMedium {
  const raw = (persona.simulation_medium || '').toLowerCase()
  if (raw === 'text' || raw === 'voice') return raw
  return persona.tts_provider?.trim() ? 'voice' : 'text'
}

export function isTextChatPersona(persona: {
  simulation_medium?: string | null
  tts_provider?: string | null
}): boolean {
  return personaSimulationMedium(persona) === 'text'
}

export function isVoicePersona(persona: {
  simulation_medium?: string | null
  tts_provider?: string | null
}): boolean {
  return personaSimulationMedium(persona) === 'voice'
}

export function filterPersonasByMedium<
  T extends { simulation_medium?: string | null; tts_provider?: string | null },
>(items: T[], medium: PersonaMediumFilter): T[] {
  return medium === 'chat' ? items.filter(isTextChatPersona) : items.filter(isVoicePersona)
}

export function simulationMediumForFilter(medium: PersonaMediumFilter): PersonaSimulationMedium {
  return medium === 'chat' ? 'text' : 'voice'
}
