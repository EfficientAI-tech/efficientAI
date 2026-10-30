import { Link } from 'react-router-dom'
import { X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { callFailed, callGlobalValue } from './callFailed'
import { callToFlowGraph, evidenceNodeId } from './callFlow'
import CallFlowStrip from './CallFlowStrip'
import CallTranscript from './CallTranscript'
import { dashboardApi, useDataSourceKey } from './dashboardApi'
import { formatGlobalValue, globalMetricById, STRIP_METRIC_IDS } from './globalMetrics'
import { MOCK_METRICS } from './mockCatalog'
import { isMockDataEnabled } from './mockMode'
import AgentFlowChart from '../../promptPartials/components/AgentFlowChart'
import type { MockCall } from './mockCalls'
import type { ReactNode } from 'react'

const QUALITY_METRICS = MOCK_METRICS.filter((metric) => metric.category === 'quality' && metric.kind !== 'category')
const OUTCOME_METRICS = MOCK_METRICS.filter((metric) => metric.category === 'quality' && metric.kind === 'category')
const INSIGHT_METRICS = MOCK_METRICS.filter((metric) => metric.category === 'user_insight')

export default function CallDetailDrawer({
  callId,
  metricId,
  onClose,
}: {
  callId: string
  metricId: string
  onClose: () => void
}) {
  const source = useDataSourceKey()
  const { data: call } = useQuery({
    queryKey: ['dashboard-call', source, callId],
    queryFn: () => dashboardApi.getCall(callId),
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" className="flex-1 bg-gray-900/30" aria-label="Close call" onClick={onClose} />
      <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-gray-100 bg-white px-5 py-4">
          <div>
            <p className="text-xs text-gray-500">{call?.agentName ?? 'Call'}</p>
            <h2 className="text-lg font-semibold text-gray-900">
              {call?.scenarioName ?? (call?.source === 'live' ? 'Live call' : 'Simulation')}
            </h2>
            {call && (
              <p className="mt-1 text-sm text-gray-600">
                {new Date(call.startedAt).toLocaleString()} · {call.durationSeconds}s
                {call.endedReason ? ` · ${call.endedReason}` : ''}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        {!call ? (
          <p className="px-5 py-8 text-sm text-gray-500">Call not found.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_240px] gap-4 px-5 py-5">
            <div className="space-y-4 min-w-0">
              <CallFlowStrip call={call} metricId={metricId} />
              <details className="rounded-xl border border-gray-200 bg-white">
                <summary className="cursor-pointer px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  Node graph
                </summary>
                <div className="h-80 border-t border-gray-100">
                  <AgentFlowChart
                    data={callToFlowGraph(call, metricId)}
                    height={320}
                    title="Call flow"
                    highlightNodeId={evidenceNodeId(call, metricId)}
                  />
                </div>
              </details>
              <section className="rounded-xl border border-gray-200 bg-white p-3">
                <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Transcript</p>
                <CallTranscript call={call} metricId={metricId} />
              </section>
            </div>
            <CallMetricsPanel call={call} metricId={metricId} />
          </div>
        )}
      </aside>
    </div>
  )
}

function CallMetricsPanel({ call, metricId }: { call: MockCall; metricId: string }) {
  const globalDefs = STRIP_METRIC_IDS.map((id) => globalMetricById(id)).filter(
    (metric): metric is NonNullable<typeof metric> => Boolean(metric?.clickable),
  )

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Per-call metrics</h3>
      <MetricSection title="Global">
        {globalDefs.map((metric) => (
          <div key={metric.id}>
            <MetricRow
              label={metric.name}
              value={formatGlobalValue(metric, callGlobalValue(call, metric.id))}
              failed={callFailed(call, metric.id)}
              active={metricId === metric.id}
            />
            {metric.subMetricIds?.map((subId) => {
              const sub = globalMetricById(subId)
              if (!sub) return null
              return (
                <MetricRow
                  key={sub.id}
                  label={sub.name}
                  value={formatGlobalValue(sub, callGlobalValue(call, sub.id))}
                  failed={callFailed(call, sub.id)}
                  active={metricId === sub.id}
                  nested
                />
              )
            })}
          </div>
        ))}
      </MetricSection>
      <MetricSection title="Local quality">
        {QUALITY_METRICS.map((metric) => (
          <LocalMetricRow key={metric.id} call={call} metricId={metric.id} activeId={metricId} />
        ))}
      </MetricSection>
      <MetricSection title="Call outcome">
        {OUTCOME_METRICS.map((metric) => (
          <LocalMetricRow key={metric.id} call={call} metricId={metric.id} activeId={metricId} />
        ))}
      </MetricSection>
      <MetricSection title="Insights">
        {INSIGHT_METRICS.map((metric) => (
          <LocalMetricRow key={metric.id} call={call} metricId={metric.id} activeId={metricId} />
        ))}
      </MetricSection>
      {!isMockDataEnabled() && (
        <Link to={`/results/${call.id}`} className="inline-block text-xs font-medium text-gray-800 underline">
          Open full run
        </Link>
      )}
    </div>
  )
}

function MetricSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-gray-100 bg-gray-50/70 px-2.5 py-2">
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">{title}</p>
      <div className="space-y-1">{children}</div>
    </section>
  )
}

function LocalMetricRow({
  call,
  metricId,
  activeId,
}: {
  call: MockCall
  metricId: string
  activeId: string
}) {
  const score = call.metric_scores[metricId]
  if (!score) return null
  return (
    <MetricRow
      label={score.metric_name}
      value={String(score.value)}
      failed={score.failed}
      active={activeId === metricId}
    />
  )
}

function MetricRow({
  label,
  value,
  failed,
  active,
  nested,
}: {
  label: string
  value: string
  failed?: boolean
  active?: boolean
  nested?: boolean
}) {
  return (
    <div
      className={`flex justify-between gap-2 rounded-md px-1.5 py-1 text-xs ${
        nested ? 'ml-2' : ''
      } ${active ? 'bg-indigo-50 text-indigo-950' : ''} ${failed && !active ? 'text-rose-700' : 'text-gray-700'}`}
    >
      <span className={active ? 'text-indigo-700' : 'text-gray-500'}>{label}</span>
      <span className={`tabular-nums font-medium ${failed ? 'text-rose-700' : ''}`}>{value}</span>
    </div>
  )
}
