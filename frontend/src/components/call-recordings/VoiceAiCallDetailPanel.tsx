import { useMemo, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Clock, DollarSign, FileText, ListTree, Loader, MessageSquare, Sparkles } from 'lucide-react'
import { apiClient } from '../../lib/api'
import CallWaveformPlayer from './CallWaveformPlayer'
import { ProviderCostPanel, ProviderLatencyPanel } from './ProviderMetricsPanels'
import VapiCallDetails, { type VapiDetailSection } from './VapiCallDetails'
import RetellCallDetails, { type RetellDetailSection } from './RetellCallDetails'
import ElevenLabsCallDetails from './ElevenLabsCallDetails'
import SmallestCallDetails from './SmallestCallDetails'
import CallEventTimeline from './CallEventTimeline'
import {
  buildRetellCallTimeline,
  buildVapiCallTimeline,
} from './callTimelineUtils'

type DrawerTab = 'transcript' | 'cost' | 'latency' | 'logs' | 'analysis'
type LogsView = 'timeline' | 'raw'

const TABS: Array<{ id: DrawerTab; label: string; icon: typeof FileText }> = [
  { id: 'transcript', label: 'Transcript', icon: MessageSquare },
  { id: 'cost', label: 'Cost', icon: DollarSign },
  { id: 'latency', label: 'Latency', icon: Clock },
  { id: 'logs', label: 'Logs', icon: ListTree },
  { id: 'analysis', label: 'Analysis', icon: Sparkles },
]

function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  const mins = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  if (mins > 0) return `${mins}m ${sec}s`
  return `${sec}s`
}

function extractCost(recording: { call_data?: Record<string, unknown> }): number | null {
  const data = recording.call_data as Record<string, unknown> | undefined
  if (!data) return null
  if (typeof data.cost === 'number') return data.cost
  const breakdown = (data.cost_breakdown || data.costBreakdown) as { total?: number } | undefined
  if (typeof breakdown?.total === 'number') return breakdown.total
  return null
}

function extractDurationSeconds(recording: { call_data?: Record<string, unknown> }): number | null {
  const data = recording.call_data as Record<string, unknown> | undefined
  if (!data) return null
  if (typeof data.duration_seconds === 'number') return data.duration_seconds
  if (typeof data.duration_ms === 'number') return data.duration_ms / 1000
  const started = data.startedAt || data.start_timestamp
  const ended = data.endedAt || data.end_timestamp
  if (typeof started === 'string' && typeof ended === 'string') {
    const startMs = Date.parse(started)
    const endMs = Date.parse(ended)
    if (!Number.isNaN(startMs) && !Number.isNaN(endMs) && endMs >= startMs) {
      return (endMs - startMs) / 1000
    }
  }
  return null
}

function externalLogUrl(platform: string | undefined, callData: Record<string, unknown>): string | null {
  if (platform === 'vapi') {
    const artifact = (callData.artifact || {}) as Record<string, unknown>
    const url = artifact.presignedLogUrl || artifact.logUrl
    return url ? String(url) : null
  }
  if (platform === 'retell' && callData.public_log_url) {
    return String(callData.public_log_url)
  }
  return null
}

export default function VoiceAiCallDetailPanel({
  recording,
  callShortId,
  hideWaveform = false,
  detailsLoading = false,
}: {
  recording: {
    id?: string | null
    provider_platform?: string
    call_data?: Record<string, unknown>
    updated_at?: string | null
    evaluation?: { call_analysis?: Record<string, unknown> | null } | null
  }
  callShortId: string
  hideWaveform?: boolean
  detailsLoading?: boolean
}) {
  const [tab, setTab] = useState<DrawerTab>('transcript')
  const [logsView, setLogsView] = useState<LogsView>('timeline')
  const platform = recording.provider_platform
  const callData = (recording.call_data || {}) as Record<string, unknown>

  useEffect(() => {
    setTab('transcript')
    setLogsView('timeline')
  }, [callShortId])
  const evaluatorAnalysis = recording.evaluation?.call_analysis ?? null

  const cost = extractCost(recording)
  const durationSec = extractDurationSeconds(recording)
  const logUrl = externalLogUrl(platform, callData)

  const logEvents = useMemo(() => {
    if (tab !== 'logs' || logsView !== 'timeline') return []
    if (platform === 'vapi') return buildVapiCallTimeline(callData)
    if (platform === 'retell') return buildRetellCallTimeline(callData)
    return []
  }, [platform, callData, tab, logsView])

  const supportsRawLogs = platform === 'vapi' || platform === 'retell'
  const { data: rawLogs, isFetching: rawLogsLoading } = useQuery({
    queryKey: ['call-recording-logs', callShortId],
    queryFn: () => apiClient.getCallRecordingLogs(callShortId),
    enabled: tab === 'logs' && logsView === 'raw' && supportsRawLogs,
    staleTime: 60_000,
  })

  const renderPlatformSection = (section: VapiDetailSection | RetellDetailSection) => {
    if (platform === 'retell') {
      return (
        <RetellCallDetails
          callData={callData as any}
          section={section as RetellDetailSection}
          compact
          evaluatorAnalysis={evaluatorAnalysis}
        />
      )
    }
    if (platform === 'vapi') {
      return (
        <VapiCallDetails
          callData={callData as any}
          section={section as VapiDetailSection}
          compact
          evaluatorAnalysis={evaluatorAnalysis}
        />
      )
    }
    if (platform === 'elevenlabs') {
      return (
        <ElevenLabsCallDetails
          callData={callData as any}
          callShortId={callShortId}
          hideTranscript={section !== 'transcript'}
          hideAudio
        />
      )
    }
    if (platform === 'smallest') {
      return <SmallestCallDetails callData={callData as any} hideTranscript={section !== 'transcript'} />
    }
    return (
      <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100">
        {JSON.stringify(callData, null, 2)}
      </pre>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700">
          <DollarSign className="h-3.5 w-3.5 text-primary-600" />
          {cost != null ? `$${cost.toFixed(4)}` : 'Cost —'}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700">
          <Clock className="h-3.5 w-3.5 text-primary-600" />
          {formatDuration(durationSec)}
        </span>
        {platform ? (
          <span className="inline-flex items-center rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium capitalize text-gray-700">
            {platform}
          </span>
        ) : null}
      </div>

      {!hideWaveform ? (
        <CallWaveformPlayer
          callShortId={callShortId}
          callRecordingId={recording.id}
          callData={callData}
          platform={platform}
          audioRevision={typeof recording.updated_at === 'string' ? recording.updated_at : null}
        />
      ) : null}

      <div className="flex flex-wrap gap-1 border-b border-gray-200">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === id
                ? 'border-primary-500 text-primary-800'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      <div>
        {detailsLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
            <Loader className="h-4 w-4 animate-spin" />
            Loading call details…
          </div>
        ) : null}
        {!detailsLoading && tab === 'transcript' ? renderPlatformSection('transcript') : null}
        {!detailsLoading && tab === 'cost' ? (
          <ProviderCostPanel
            callData={callData}
            platform={platform}
            totalCost={cost}
            durationSec={durationSec}
          />
        ) : null}
        {!detailsLoading && tab === 'latency' ? (
          <ProviderLatencyPanel callData={callData} platform={platform} />
        ) : null}
        {!detailsLoading && tab === 'analysis' ? renderPlatformSection('analysis') : null}
        {!detailsLoading && tab === 'logs' ? (
          <div className="space-y-3">
            {supportsRawLogs ? (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setLogsView('timeline')}
                  className={`rounded-md border px-2.5 py-1.5 text-xs font-medium ${
                    logsView === 'timeline'
                      ? 'border-primary-300 bg-primary-50 text-primary-800'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  Timeline
                </button>
                <button
                  type="button"
                  onClick={() => setLogsView('raw')}
                  className={`rounded-md border px-2.5 py-1.5 text-xs font-medium ${
                    logsView === 'raw'
                      ? 'border-primary-300 bg-primary-50 text-primary-800'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  Raw provider logs
                </button>
              </div>
            ) : null}
            {logsView === 'raw' ? (
              rawLogsLoading ? (
                <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
                  <Loader className="h-4 w-4 animate-spin" />
                  Loading provider logs…
                </div>
              ) : rawLogs?.entries?.length ? (
                <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                  <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-500">
                    {rawLogs.count} log entries from {rawLogs.platform}
                  </div>
                  <div className="max-h-[min(70vh,560px)] overflow-y-auto">
                    {rawLogs.entries.map((entry, index) => (
                      <div
                        key={`${entry.time || 'log'}-${index}`}
                        className="border-b border-gray-50 px-4 py-3 text-sm hover:bg-gray-50/80"
                      >
                        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                          {entry.time ? <span className="font-mono">{entry.time}</span> : null}
                          {entry.level ? (
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 font-medium uppercase">
                              {entry.level}
                            </span>
                          ) : null}
                          {entry.category ? (
                            <span className="rounded bg-sky-50 px-1.5 py-0.5 text-sky-800">
                              {entry.category}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 font-medium text-gray-900">{entry.summary || 'Log event'}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <CallEventTimeline
                  events={[]}
                  externalLogUrl={logUrl}
                  emptyMessage="No raw provider logs yet. Try Refresh after the call ends."
                />
              )
            ) : (
              <CallEventTimeline
                events={logEvents}
                externalLogUrl={logUrl}
                emptyMessage="No structured logs from the provider yet. Try Refresh after the call ends."
              />
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}
