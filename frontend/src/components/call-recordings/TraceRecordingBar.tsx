import { useEffect, useState } from 'react'
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

  useEffect(() => {
    let cancelled = false

    async function load() {
      if (!callRecordingId && !evaluatorResultId) return
      setLoading(true)
      setFailed(false)
      try {
        if (callRecordingId && callShortId) {
          if (!cancelled) {
            setAudioUrl(apiClient.getCallRecordingAudioStreamUrl(callShortId))
          }
          return
        }
        if (evaluatorResultId) {
          const result = await apiClient.getEvaluatorResult(evaluatorResultId, false)
          if (!hasEvaluatorResultRecording(result)) return
          if (!cancelled) {
            setAudioUrl(apiClient.getEvaluatorResultAudioStreamUrl(evaluatorResultId))
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
        <audio controls src={audioUrl} className="h-9 w-full max-w-md" preload="auto" />
      ) : null}
    </div>
  )
}
