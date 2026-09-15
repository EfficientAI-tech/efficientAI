/** Resolve a browser-playable recording URL from provider call_data. */

export function getProviderRecordingUrl(
  callData: Record<string, unknown> | null | undefined,
  platform?: string | null,
): string | null {
  if (!callData) return null

  const plat = (platform || '').toLowerCase()

  if (plat === 'vapi') {
    const artifact = (callData.artifact || {}) as Record<string, unknown>
    const recording = (artifact.recording || {}) as Record<string, unknown>
    const mono = (recording.mono || {}) as Record<string, unknown>
    const recordingUrls = (callData.recording_urls || {}) as Record<string, unknown>

    return (
      pickString(artifact.presignedMonoUrl) ||
      pickString(artifact.presignedStereoUrl) ||
      pickString(callData.presignedMonoUrl) ||
      pickString(callData.presignedStereoUrl) ||
      pickString(callData.recordingUrl) ||
      pickString(callData.stereoRecordingUrl) ||
      pickString(artifact.recordingUrl) ||
      pickString(artifact.stereoRecordingUrl) ||
      pickString(mono.combinedUrl) ||
      pickString(recordingUrls.combined_url) ||
      pickString(recordingUrls.stereo_url) ||
      null
    )
  }

  if (plat === 'elevenlabs') {
    const recordingUrls = (callData.recording_urls || {}) as Record<string, unknown>
    return pickString(callData.recording_url) || pickString(recordingUrls.conversation_audio)
  }

  return (
    pickString(callData.recording_url) ||
    pickString(callData.recordingUrl) ||
    null
  )
}

export function hasEvaluatorResultRecording(
  result: {
    audio_s3_key?: string | null
    provider_platform?: string | null
    call_data?: Record<string, unknown> | null
  } | null | undefined,
): boolean {
  if (!result) return false
  const audioS3Key = result.audio_s3_key || pickString(result.call_data?.recording_s3_key)
  return Boolean(audioS3Key || getProviderRecordingUrl(result.call_data, result.provider_platform))
}

function pickString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export interface VapiRecordingTracks {
  stereo: string | null
  combined: string | null
  customer: string | null
  assistant: string | null
}

export function getVapiRecordingTracks(callData: Record<string, unknown> | null | undefined): VapiRecordingTracks {
  if (!callData) {
    return { stereo: null, combined: null, customer: null, assistant: null }
  }
  const artifact = (callData.artifact || {}) as Record<string, unknown>
  const recording = (artifact.recording || {}) as Record<string, unknown>
  const mono = (recording.mono || {}) as Record<string, unknown>
  const recordingUrls = (callData.recording_urls || {}) as Record<string, unknown>

  return {
    stereo:
      pickString(artifact.presignedStereoUrl) ||
      pickString(callData.presignedStereoUrl) ||
      pickString(callData.stereoRecordingUrl) ||
      pickString(artifact.stereoRecordingUrl) ||
      pickString(recordingUrls.stereo_url),
    combined:
      pickString(artifact.presignedMonoUrl) ||
      pickString(callData.presignedMonoUrl) ||
      pickString(callData.recordingUrl) ||
      pickString(artifact.recordingUrl) ||
      pickString(mono.combinedUrl) ||
      pickString(recordingUrls.combined_url),
    customer: pickString(mono.customerUrl) || pickString(recordingUrls.customer_url),
    assistant: pickString(mono.assistantUrl) || pickString(recordingUrls.assistant_url),
  }
}
