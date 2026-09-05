export type VoiceAiPlatformId = 'vapi' | 'retell' | 'elevenlabs' | 'smallest' | (string & {})

export interface VoiceProviderCapabilities {
  label: string
  supportsRawLogs: boolean
  supportsTimelineLogs: boolean
  /** Provider call id is assigned client-side after the session starts (Vapi, ElevenLabs). */
  requiresClientProviderCallId: boolean
}

const DEFAULT_CAPABILITIES: VoiceProviderCapabilities = {
  label: 'Provider',
  supportsRawLogs: false,
  supportsTimelineLogs: false,
  requiresClientProviderCallId: false,
}

export const VOICE_PROVIDER_REGISTRY: Record<string, VoiceProviderCapabilities> = {
  vapi: {
    label: 'Vapi',
    supportsRawLogs: true,
    supportsTimelineLogs: true,
    requiresClientProviderCallId: true,
  },
  retell: {
    label: 'Retell',
    supportsRawLogs: true,
    supportsTimelineLogs: true,
    requiresClientProviderCallId: false,
  },
  elevenlabs: {
    label: 'ElevenLabs',
    supportsRawLogs: false,
    supportsTimelineLogs: true,
    requiresClientProviderCallId: true,
  },
  smallest: {
    label: 'Smallest',
    supportsRawLogs: false,
    supportsTimelineLogs: true,
    requiresClientProviderCallId: false,
  },
}

export function getVoiceProviderCapabilities(platform?: string | null): VoiceProviderCapabilities {
  const key = (platform || '').toLowerCase()
  return VOICE_PROVIDER_REGISTRY[key] ?? {
    ...DEFAULT_CAPABILITIES,
    label: key ? key.charAt(0).toUpperCase() + key.slice(1) : DEFAULT_CAPABILITIES.label,
  }
}

export function isKnownVoiceAiPlatform(platform?: string | null): boolean {
  return Boolean(platform && VOICE_PROVIDER_REGISTRY[platform.toLowerCase()])
}
