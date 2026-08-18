import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, GitBranch, Loader, AlertCircle } from 'lucide-react'
import type { ObservabilityCallTrace, ObservabilityTraceSpan } from '../../types/api'
import TraceTree from './TraceTree'
import DualTrackWaveformPlayer, {
  type DualTrackWaveformPlayerHandle,
} from './DualTrackWaveformPlayer'
import {
  buildSpanTree,
  findNearestTurnSpan,
  flattenSpanTree,
  getTraceRootStartMs,
  spanOffsetSec,
} from './traceDisplay'
import type { WaveformSegment } from './waveformSegments'
import { useObservabilityCallAudioBlob } from '../../hooks/useObservabilityCallAudioBlob'
import { useObservabilityLiveAudio } from '../../hooks/useObservabilityLiveAudio'

export interface TraceRecordingPanelProps {
  callShortId: string
  traceId: string | null
  callTrace: ObservabilityCallTrace | undefined
  traceLoading: boolean
  traceError: boolean
  traceErrorDisplay: { title: string; body: string; hint?: string }
  playbackUrl: string | null
  audioLoading: boolean
  isLiveCall?: boolean
  callStartMs: number | null
  waveformSegments: WaveformSegment[]
  agentLabel: string
  hasStorageRecording: boolean
  fallbackDurationSec?: number | null
  onRefreshTrace: () => void
  selectedSpanId?: string | null
  onSelectedSpanIdChange?: (spanId: string | null) => void
}

export default function TraceRecordingPanel({
  callShortId,
  traceId,
  callTrace,
  traceLoading,
  traceError,
  traceErrorDisplay,
  playbackUrl,
  audioLoading,
  isLiveCall = false,
  callStartMs,
  waveformSegments,
  agentLabel,
  hasStorageRecording,
  fallbackDurationSec,
  onRefreshTrace,
  selectedSpanId: externalSelectedSpanId,
  onSelectedSpanIdChange,
}: TraceRecordingPanelProps) {
  const waveformRef = useRef<DualTrackWaveformPlayerHandle>(null)
  const [audioCurrentTimeSec, setAudioCurrentTimeSec] = useState(0)
  const [internalSelectedSpanId, setInternalSelectedSpanId] = useState<string | null>(null)
  const selectedSpanId = externalSelectedSpanId ?? internalSelectedSpanId

  const { data: blobAudioUrl, isLoading: blobLoading } = useObservabilityCallAudioBlob(
    callShortId,
    hasStorageRecording && !isLiveCall,
  )

  const {
    data: liveAudio,
    isLoading: liveAudioLoading,
    isFetching: liveAudioFetching,
    isError: liveAudioUnavailable,
  } = useObservabilityLiveAudio(callShortId, isLiveCall)

  const waveformAudioUrl = isLiveCall ? liveAudio?.blobUrl : blobAudioUrl || playbackUrl
  const liveDurationSec = isLiveCall ? liveAudio?.durationSec ?? null : null

  const allSpans = useMemo(() => {
    if (!callTrace) return []
    return flattenSpanTree(buildSpanTree(callTrace))
  }, [callTrace])

  const rootStartMs = useMemo(() => getTraceRootStartMs(allSpans), [allSpans])

  const setSelectedSpanId = useCallback(
    (spanId: string | null) => {
      if (onSelectedSpanIdChange) onSelectedSpanIdChange(spanId)
      else setInternalSelectedSpanId(spanId)
    },
    [onSelectedSpanIdChange],
  )

  const seekAudio = useCallback((sec: number) => {
    waveformRef.current?.seek(sec)
  }, [])

  const handleSelectSpan = useCallback(
    (span: ObservabilityTraceSpan) => {
      if (!span.span_id) return
      setSelectedSpanId(span.span_id)
      if (span.name === 'turn' || span.name === 'conversation') {
        const offset = spanOffsetSec(span, callStartMs, rootStartMs)
        if (offset !== null) seekAudio(offset)
      }
    },
    [callStartMs, rootStartMs, seekAudio, setSelectedSpanId],
  )

  const handleAudioTimeUpdate = useCallback(
    (timeSec: number) => {
      setAudioCurrentTimeSec(timeSec)
      if (!callTrace || allSpans.length === 0) return
      const nearest = findNearestTurnSpan(timeSec, callStartMs, rootStartMs, allSpans)
      if (nearest?.span_id && nearest.span_id !== selectedSpanId) {
        setSelectedSpanId(nearest.span_id)
      }
    },
    [allSpans, callStartMs, callTrace, rootStartMs, selectedSpanId, setSelectedSpanId],
  )

  useEffect(() => {
    if (!externalSelectedSpanId) return
    const span = allSpans.find((s) => s.span_id === externalSelectedSpanId)
    if (!span?.span_id) return
    if (internalSelectedSpanId !== externalSelectedSpanId && onSelectedSpanIdChange === undefined) {
      setInternalSelectedSpanId(externalSelectedSpanId)
    }
    if (waveformAudioUrl && (span.name === 'turn' || span.name === 'conversation')) {
      const offset = spanOffsetSec(span, callStartMs, rootStartMs)
      if (offset !== null) seekAudio(offset)
    }
  }, [
    externalSelectedSpanId,
    allSpans,
    callStartMs,
    rootStartMs,
    waveformAudioUrl,
    seekAudio,
    onSelectedSpanIdChange,
    internalSelectedSpanId,
  ])

  const liveAudioBlobUrl = liveAudio?.blobUrl ?? null
  const effectiveTraceId = traceId || callTrace?.trace_id || null

  const recordingLoading = isLiveCall
    ? liveAudioLoading && !liveAudioBlobUrl
    : audioLoading || (hasStorageRecording && blobLoading && !blobAudioUrl)

  return (
    <div className="space-y-4">
      {(waveformAudioUrl || recordingLoading || (isLiveCall && !liveAudioUnavailable)) && (
        <div className="sticky top-0 z-10">
          {recordingLoading ? (
            <div className="rounded-xl border border-gray-100 bg-gray-50/40 p-4 flex items-center gap-2 text-sm text-gray-500">
              <Loader className="w-4 h-4 animate-spin" />
              {isLiveCall ? 'Waiting for live audio…' : 'Loading recording…'}
            </div>
          ) : waveformAudioUrl ? (
            <>
              <DualTrackWaveformPlayer
                ref={waveformRef}
                audioUrl={waveformAudioUrl}
                segments={waveformSegments}
                agentLabel={agentLabel}
                userLabel="Customer"
                fallbackDurationSec={fallbackDurationSec}
                liveMode={isLiveCall}
                liveDurationSec={liveDurationSec}
                onTimeUpdate={handleAudioTimeUpdate}
              />
              {isLiveCall && liveAudioFetching && (
                <p className="text-[11px] text-gray-400 mt-1">Refreshing live audio…</p>
              )}
              {!isLiveCall && playbackUrl && (
                <div className="mt-2 flex justify-end">
                  <a
                    href={playbackUrl}
                    download={`call_${callShortId}.wav`}
                    className="inline-flex items-center gap-2 text-xs text-indigo-600 hover:text-indigo-800"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download recording
                  </a>
                </div>
              )}
              {callTrace && callTrace.spans.length > 0 && (
                <p className="text-[11px] text-gray-500 mt-2">
                  {isLiveCall
                    ? 'Live audio and trace update during the call. Scrub the waveform or click turns to seek.'
                    : 'Scrub the waveform to jump between turns, or click a turn in the trace tree to seek audio.'}
                </p>
              )}
            </>
          ) : isLiveCall ? (
            <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 p-4 text-center text-xs text-gray-500">
              Live audio will appear once the call captures enough audio.
            </div>
          ) : null}
        </div>
      )}

      <div>
        <div className="flex items-center justify-between gap-3 mb-3">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-indigo-500" />
            Execution Trace
          </h3>
          {effectiveTraceId && (
            <button
              type="button"
              onClick={onRefreshTrace}
              disabled={traceLoading}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium disabled:opacity-50"
            >
              {traceLoading ? 'Refreshing…' : 'Refresh trace'}
            </button>
          )}
        </div>

        {traceLoading ? (
          <div className="flex items-center justify-center py-12 text-sm text-gray-500">
            <Loader className="w-5 h-5 text-indigo-500 animate-spin mr-2" />
            Loading trace spans…
          </div>
        ) : traceError ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-amber-900">{traceErrorDisplay.title}</p>
                <p className="text-xs text-amber-800 mt-1">
                  Trace ID <span className="font-mono">{effectiveTraceId ?? 'N/A'}</span>. {traceErrorDisplay.body}
                </p>
                {traceErrorDisplay.hint && (
                  <p className="text-xs text-amber-700 mt-2">{traceErrorDisplay.hint}</p>
                )}
              </div>
            </div>
          </div>
        ) : callTrace && callTrace.spans.length > 0 ? (
          <TraceTree
            trace={callTrace}
            embedded
            callStartMs={callStartMs}
            audioCurrentTimeSec={waveformAudioUrl ? audioCurrentTimeSec : null}
            selectedSpanId={selectedSpanId}
            onSelectSpan={handleSelectSpan}
            showTimeline
            syncAudioToSelection={!!waveformAudioUrl}
          />
        ) : !effectiveTraceId ? (
          <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 p-6 text-center">
            <GitBranch className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm font-medium text-gray-700">No trace linked to this call</p>
            <p className="text-xs text-gray-500 mt-1 max-w-xl mx-auto">
              Internal EfficientAI voice-bundle calls record a trace automatically when tracing is enabled.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 p-6 text-center">
            <p className="text-sm font-medium text-gray-700">No spans found for this trace</p>
            <p className="text-xs text-gray-500 mt-1">
              Trace ID <span className="font-mono">{effectiveTraceId ?? 'N/A'}</span> was saved, but the trace store returned no spans.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
