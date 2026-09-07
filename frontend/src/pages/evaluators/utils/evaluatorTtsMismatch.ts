export interface TtsMismatchPersona {
  name?: string | null
  tts_provider?: string | null
}

export interface TtsMismatchSuiteLike {
  voice_bundle_tts_provider?: string | null
  personas?: TtsMismatchPersona[]
}

export function getSuiteTtsMismatchedPersonas(suite: TtsMismatchSuiteLike): TtsMismatchPersona[] {
  const bundleProvider = suite.voice_bundle_tts_provider?.trim().toLowerCase()
  if (!bundleProvider) return []
  return (suite.personas ?? []).filter((persona) => {
    const personaProvider = persona.tts_provider?.trim().toLowerCase()
    return Boolean(personaProvider && personaProvider !== bundleProvider)
  })
}

export function suiteHasTtsProviderMismatch(suite: TtsMismatchSuiteLike): boolean {
  return getSuiteTtsMismatchedPersonas(suite).length > 0
}

export function formatTtsMismatchMessage(
  suite: TtsMismatchSuiteLike,
  mismatched?: TtsMismatchPersona[],
): string {
  const stale = mismatched ?? getSuiteTtsMismatchedPersonas(suite)
  const bundleProvider = suite.voice_bundle_tts_provider ?? 'unknown'
  if (stale.length === 0) return ''
  const personaLabel = stale.map((p) => p.name || 'Unknown').join(', ')
  const personaProviders = [...new Set(stale.map((p) => p.tts_provider).filter(Boolean))].join(', ')
  return (
    `The TTS provider on this agent's voice bundle changed to '${bundleProvider}'. ` +
    `Persona${stale.length > 1 ? 's' : ''} '${personaLabel}' still use${stale.length > 1 ? '' : 's'} ` +
    `'${personaProviders}'. Edit the evaluator and choose a persona that matches the new TTS provider.`
  )
}

export function formatInboundTtsMismatchMessage(suite: TtsMismatchSuiteLike): string {
  if (!suiteHasTtsProviderMismatch(suite)) return ''
  const base = formatTtsMismatchMessage(suite)
  return `${base} Until then, inbound calls will use the voice bundle's default voice for the agent leg.`
}
