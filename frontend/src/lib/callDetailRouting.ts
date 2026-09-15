const VOICE_AI_PLATFORMS = new Set(['vapi', 'retell', 'elevenlabs', 'smallest'])

export function isVoiceAiProviderPlatform(platform?: string | null): boolean {
  return VOICE_AI_PLATFORMS.has((platform || '').toLowerCase())
}

export function isPlaygroundCallRecordingSource(source?: string | null): boolean {
  return (source || '').toLowerCase() === 'playground'
}

export function isWebhookCallRecordingSource(source?: string | null): boolean {
  return (source || '').toLowerCase() === 'webhook'
}

export function resolveTraceDrawerTargets(input: {
  callShortId?: string | null
  providerPlatform?: string | null
  callRecordingSource?: string | null
  evaluatorResultId?: string | null
  syntheticTraceId?: string | null
}): {
  callShortId: string | null
  observabilityCallShortId: string | null
  evaluatorResultId: string | null
  traceId: string | null
} {
  const callShortId = input.callShortId || null
  const platform = input.providerPlatform
  const source = input.callRecordingSource

  if (callShortId && isVoiceAiProviderPlatform(platform) && isPlaygroundCallRecordingSource(source)) {
    return {
      callShortId,
      observabilityCallShortId: null,
      evaluatorResultId: null,
      traceId: input.syntheticTraceId || null,
    }
  }

  if (callShortId && isVoiceAiProviderPlatform(platform) && isWebhookCallRecordingSource(source)) {
    return {
      callShortId: null,
      observabilityCallShortId: callShortId,
      evaluatorResultId: null,
      traceId: input.syntheticTraceId || null,
    }
  }

  return {
    callShortId: null,
    observabilityCallShortId: null,
    evaluatorResultId: input.evaluatorResultId || null,
    traceId: input.syntheticTraceId || null,
  }
}
