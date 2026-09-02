import { useEffect, useRef, useState } from 'react'
import { Loader } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { hasEvaluatorResultRecording } from '../../lib/recordingUrls'

export default function TraceRecordingBar({
  callShortId,
  callRecordingId,
  evaluatorResultId,
}: {
  callShortId?: string | null
  callRecordingId?: string | null
  evaluatorResultId?: string | null
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const blobRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      if (!callRecordingId && !evaluatorResultId) return
      setLoading(true)
      setFailed(false)
      try {
        if (callRecordingId && callShortId) {
          const url = await apiClient.getCallRecordingAudioUrl(callShortId)
          if (!cancelled) {
            blobRef.current = url
            setAudioUrl(url)
          }
          return
        }
        if (evaluatorResultId) {
          const result = await apiClient.getEvaluatorResult(evaluatorResultId, false)
          if (!hasEvaluatorResultRecording(result)) return
          const url = await apiClient.getEvaluatorResultAudioUrl(evaluatorResultId)
          if (!cancelled) {
            blobRef.current = url
            setAudioUrl(url)
          }
        }
      } catch {
        if (!cancelled) setFailed(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
      if (blobRef.current) URL.revokeObjectURL(blobRef.current)
    }
  }, [callRecordingId, callShortId, evaluatorResultId])

  if (!callRecordingId && !evaluatorResultId) return null
  if (failed) return null

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/80 px-4 py-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400">Recording</p>
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Loader className="h-4 w-4 animate-spin" />
          Loading audio…
        </div>
      ) : audioUrl ? (
        <audio controls src={audioUrl} className="h-9 w-full max-w-md" preload="metadata" />
      ) : null}
    </div>
  )
}
