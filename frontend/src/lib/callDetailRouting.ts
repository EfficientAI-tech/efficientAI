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

export function resolveEvaluatorAudioPlayback(input: {
  callShortId?: string | null
  providerPlatform?: string | null
  callRecordingSource?: string | null
  evaluatorResultId: string
}): {
  callShortId?: string
  observabilityCallShortId?: string
  evaluatorResultId?: string
} {
  const callShortId = input.callShortId?.trim() || null
  const platform = input.providerPlatform
  const source = input.callRecordingSource

  if (
    callShortId &&
    isVoiceAiProviderPlatform(platform) &&
    isWebhookCallRecordingSource(source)
  ) {
    return { observabilityCallShortId: callShortId }
  }

  if (callShortId && isVoiceAiProviderPlatform(platform)) {
    return { callShortId }
  }

  if (callShortId && isPlaygroundCallRecordingSource(source)) {
    const plat = (platform || '').toLowerCase()
    if ((plat === 'voice_bundle' || plat === 'custom_websocket') && input.evaluatorResultId) {
      return { evaluatorResultId: input.evaluatorResultId }
    }
    return { callShortId }
  }

  const routed = resolveTraceDrawerTargets({
    callShortId,
    providerPlatform: platform,
    callRecordingSource: source,
    evaluatorResultId: input.evaluatorResultId,
  })
  if (routed.callShortId) {
    return { callShortId: routed.callShortId }
  }
  if (routed.observabilityCallShortId) {
    return { observabilityCallShortId: routed.observabilityCallShortId }
  }
  return { evaluatorResultId: input.evaluatorResultId }
}
