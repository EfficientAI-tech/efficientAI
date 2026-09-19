import { apiClient } from './api'

export async function linkProviderCallId(
  callShortId: string,
  providerCallId: string,
): Promise<boolean> {
  if (!callShortId?.trim() || !providerCallId?.trim()) return false
  try {
    await apiClient.updateCallRecording(callShortId, providerCallId)
    return true
  } catch {
    return false
  }
}

export function scheduleCallRecordingRefresh(
  callShortId: string,
  options?: { delayMs?: number },
): void {
  if (!callShortId) return
  const delayMs = options?.delayMs ?? 4000
  window.setTimeout(() => {
    void apiClient.refreshCallRecording(callShortId).catch(() => undefined)
  }, delayMs)
}

export async function captureElevenLabsConversationId(
  conversation: { getId?: () => string | null | undefined } | null | undefined,
  callShortId: string | null,
): Promise<boolean> {
  const conversationId = conversation?.getId?.()
  if (!callShortId || !conversationId) return false
  return linkProviderCallId(callShortId, conversationId)
}
