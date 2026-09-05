import { RefreshCw } from 'lucide-react'
import { getVoiceProviderCapabilities } from '../../lib/voiceProviderRegistry'
import { hasEnrichedCallRecordingDetails } from '../../lib/callRecordingDetails'

export default function VoiceProviderEmptyState({
  recording,
  platform,
  onRefresh,
  refreshing = false,
}: {
  recording: Record<string, unknown>
  platform?: string | null
  onRefresh?: () => void
  refreshing?: boolean
}) {
  const caps = getVoiceProviderCapabilities(platform)
  const providerCallId = recording.provider_call_id
  const status = String(recording.status ?? '').toLowerCase()
  const needsProviderLink = caps.requiresClientProviderCallId && !providerCallId

  let title = 'Call details not available yet'
  let description =
    'Provider metrics, transcript, and recording appear after the call ends. Use Refresh to sync from the provider.'

  if (needsProviderLink) {
    title = 'Waiting for provider call link'
    description =
      'This call was started from Agents Talk but was not linked to the voice provider session. End the call from the talk panel, or start a new test call — details will sync automatically after hangup.'
  } else if (status === 'pending') {
    title = 'Call in progress or awaiting provider data'
    description =
      'If the call has ended, use Refresh to pull transcript, audio, and metrics from the provider. Processing can take a few seconds.'
  } else if (!hasEnrichedCallRecordingDetails(recording)) {
    title = `${caps.label} data not synced yet`
    description =
      'Use Refresh to fetch the latest transcript, recording, and analysis from the provider.'
  }

  return (
    <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-10 text-center">
      <p className="text-sm font-medium text-gray-900">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">{description}</p>
      {onRefresh ? (
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing || (needsProviderLink && !providerCallId)}
          className="mt-5 inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh from provider
        </button>
      ) : null}
    </div>
  )
}
