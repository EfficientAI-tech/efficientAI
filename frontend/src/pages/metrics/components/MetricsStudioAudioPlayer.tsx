import { useEffect, useState } from 'react'
import { Volume2 } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import RecordingAudioPlayer from '../../../components/audio/RecordingAudioPlayer'

type MetricsStudioAudioPlayerProps = {
  sourceKind: string
  sourceRef: string
  metadata: Record<string, unknown>
}

const AUTH_GATED_PROVIDERS = new Set(['elevenlabs', 'vapi'])

function pickString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export default function MetricsStudioAudioPlayer({
  sourceKind,
  sourceRef,
  metadata,
}: MetricsStudioAudioPlayerProps) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null

    async function loadAudio() {
      setLoading(true)
      setError(null)
      setAudioUrl(null)

      try {
        const s3Key =
          pickString(metadata.audio_s3_key) ?? pickString(metadata.recording_s3_key)
        if (s3Key) {
          const { url } = await apiClient.getS3PresignedUrl(s3Key)
          if (!cancelled) setAudioUrl(url)
          return
        }

        if (sourceKind === 'call_recording' && sourceRef) {
          const source = pickString(metadata.source)?.toLowerCase()
          objectUrl =
            source === 'webhook'
              ? await apiClient.getObservabilityCallAudioUrl(sourceRef)
              : await apiClient.getCallRecordingAudioUrl(sourceRef)
          if (!cancelled) setAudioUrl(objectUrl)
          return
        }

        if (sourceKind === 'evaluator_result' && sourceRef) {
          const result = await apiClient.getEvaluatorResult(sourceRef)
          const resultS3Key = pickString(result?.audio_s3_key)
          if (resultS3Key) {
            const { url } = await apiClient.getS3PresignedUrl(resultS3Key)
            if (!cancelled) setAudioUrl(url)
            return
          }

          const provider = (result?.provider_platform || '').toLowerCase()
          if (AUTH_GATED_PROVIDERS.has(provider)) {
            objectUrl = await apiClient.getEvaluatorResultAudioUrl(sourceRef)
            if (!cancelled) setAudioUrl(objectUrl)
            return
          }

          const callDataUrl = pickString(result?.call_data?.recording_url)
          if (callDataUrl && !cancelled) {
            setAudioUrl(callDataUrl)
          }
          return
        }

        const providerUrl = pickString(metadata.recording_url)
        if (providerUrl && !cancelled) {
          setAudioUrl(providerUrl)
        }
      } catch {
        if (!cancelled) setError('Could not load recording')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void loadAudio()

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [sourceKind, sourceRef, metadata])

  if (loading) {
    return (
      <p className="text-xs text-gray-500 rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
        Loading recording…
      </p>
    )
  }

  if (error || !audioUrl) return null

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-4 space-y-2">
      <div className="flex items-center gap-2">
        <Volume2 className="h-4 w-4 text-gray-500" />
        <h4 className="text-sm font-semibold text-gray-900">Call recording</h4>
      </div>
      <RecordingAudioPlayer src={audioUrl} downloadUrl={audioUrl} />
    </div>
  )
}
