function readCallData(recording: Record<string, unknown> | null | undefined): Record<string, unknown> | null {
  const callData = recording?.call_data
  if (!callData || typeof callData !== 'object') return null
  return callData as Record<string, unknown>
}

export function hasTranscriptInCallData(data: Record<string, unknown>): boolean {
  return (
    (typeof data.transcript === 'string' && data.transcript.trim().length > 0) ||
    (typeof data.transcriptText === 'string' && data.transcriptText.trim().length > 0) ||
    (Array.isArray(data.transcript_object) && data.transcript_object.length > 0) ||
    (Array.isArray(data.messages) && data.messages.length > 0) ||
    (Array.isArray((data.artifact as Record<string, unknown> | undefined)?.messages) &&
      ((data.artifact as { messages: unknown[] }).messages?.length ?? 0) > 0)
  )
}

export function hasRecordingUrlInCallData(data: Record<string, unknown>): boolean {
  return (
    (typeof data.recordingUrl === 'string' && data.recordingUrl.trim().length > 0) ||
    (typeof data.recording_url === 'string' && data.recording_url.trim().length > 0) ||
    (typeof data.stereoRecordingUrl === 'string' && data.stereoRecordingUrl.trim().length > 0) ||
    (typeof data.stereo_recording_url === 'string' && data.stereo_recording_url.trim().length > 0) ||
    (typeof (data.artifact as Record<string, unknown> | undefined)?.recordingUrl === 'string' &&
      String((data.artifact as { recordingUrl: string }).recordingUrl).trim().length > 0) ||
    (typeof (data.recording_urls as Record<string, unknown> | undefined)?.conversation_audio ===
      'string' &&
      String((data.recording_urls as { conversation_audio: string }).conversation_audio).trim()
        .length > 0)
  )
}

/** Strict gate: skip refetch only when transcript or recording URL is present. */
export function hasEnrichedCallRecordingDetails(
  recording: Record<string, unknown> | null | undefined,
): boolean {
  const data = readCallData(recording)
  if (!data) return false
  return hasTranscriptInCallData(data) || hasRecordingUrlInCallData(data)
}

/** UI placeholder gate: enriched payload or ended call with substantive fields. */
export function hasCallRecordingDetails(
  recording: Record<string, unknown> | null | undefined,
): boolean {
  const data = readCallData(recording)
  if (!data) return false
  if (Object.keys(data).length === 0) return false
  if (hasEnrichedCallRecordingDetails(recording)) return true

  const status = String(recording?.status ?? data.status ?? '').toLowerCase()
  const ended =
    ['ended', 'completed', 'done', 'failed'].includes(status) ||
    Boolean(data.endedAt || data.ended_at || data.endedReason || data.end_timestamp)

  return ended && Object.keys(data).length >= 3
}
