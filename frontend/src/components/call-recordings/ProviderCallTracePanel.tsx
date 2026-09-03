import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getCallRecordingPlaceholder, hasCallRecordingDetails } from '../../lib/callRecordingQuery'
import { preferStereoWaveform, prefetchCallRecordingAudio } from '../../lib/waveformAudioCache'
import VoiceAiCallDetailPanel from './VoiceAiCallDetailPanel'

interface ProviderCallTracePanelProps {
  callShortId: string
  onClose?: () => void
}

export default function ProviderCallTracePanel({ callShortId, onClose }: ProviderCallTracePanelProps) {
  const queryClient = useQueryClient()

  const { data: recording, isError, error, isFetching } = useQuery({
    queryKey: ['call-recording', callShortId],
    queryFn: () => apiClient.getCallRecording(callShortId),
    enabled: Boolean(callShortId),
    placeholderData: () => getCallRecordingPlaceholder(queryClient, callShortId),
    staleTime: 30_000,
    refetchOnMount: (query) =>
      hasCallRecordingDetails(query.state.data as Record<string, unknown> | undefined)
        ? true
        : 'always',
  })

  useEffect(() => {
    if (!callShortId) return
    const stereo = preferStereoWaveform(recording?.call_data, recording?.provider_platform)
    prefetchCallRecordingAudio(callShortId, stereo)
    if (!stereo) prefetchCallRecordingAudio(callShortId, false)
  }, [callShortId, recording?.call_data, recording?.provider_platform])

  const handleRefresh = async () => {
    await apiClient.refreshCallRecording(callShortId)
    await queryClient.invalidateQueries({ queryKey: ['call-recording', callShortId] })
  }

  const errorMessage =
    isError && error
      ? (error as { response?: { data?: { detail?: string } }; message?: string }).response?.data
          ?.detail ||
        (error as { message?: string }).message ||
        'Failed to load call'
      : null

  const platform = recording?.provider_platform
  const platformLabel =
    platform === 'retell'
      ? 'Retell'
      : platform === 'vapi'
        ? 'Vapi'
        : platform === 'elevenlabs'
          ? 'ElevenLabs'
          : platform === 'smallest'
            ? 'Smallest'
            : platform || 'Provider'

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-mono text-xl font-bold tracking-tight text-primary-600">
              #{callShortId}
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              {platformLabel} provider metrics and transcript
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isFetching}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            {onClose ? (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
              >
                <X className="h-5 w-5" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {errorMessage ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {errorMessage}
          </div>
        ) : recording ? (
          <VoiceAiCallDetailPanel
            recording={recording as Parameters<typeof VoiceAiCallDetailPanel>[0]['recording']}
            callShortId={callShortId}
            detailsLoading={isFetching && !hasCallRecordingDetails(recording as Record<string, unknown>)}
          />
        ) : null}
      </div>
    </div>
  )
}
