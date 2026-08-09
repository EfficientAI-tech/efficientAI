import type { ReactNode } from 'react'
import { AudioWaveform, Brain, Sparkles } from 'lucide-react'
import {
  filterVisibleMetricScores,
  type MetricScoreEntry,
} from '../utils/metricScoreFilters'

type MetricScoreGridProps = {
  metricScores: Record<string, MetricScoreEntry>
  metricNameById?: Record<string, string>
  childMetricIds?: Set<string>
  draftMetricIds?: Set<string>
  onPromoteDraft?: (metricId: string) => void
}

const METRIC_CATEGORIES: Record<string, 'acoustic' | 'ai_voice' | 'llm'> = {
  'Pitch Variance': 'acoustic',
  Jitter: 'acoustic',
  Shimmer: 'acoustic',
  HNR: 'acoustic',
  'MOS Score': 'ai_voice',
  'Emotion Category': 'ai_voice',
  'Emotion Confidence': 'ai_voice',
  Valence: 'ai_voice',
  Arousal: 'ai_voice',
  'Speaker Consistency': 'ai_voice',
  'Prosody Score': 'ai_voice',
}

function getCategory(metricName: string): 'acoustic' | 'ai_voice' | 'llm' {
  return METRIC_CATEGORIES[metricName] ?? 'llm'
}

function formatMetricValue(value: unknown, type: string | undefined, _metricName: string): ReactNode {
  if (value === null || value === undefined) return <span className="text-gray-300">—</span>

  const normalizedType = type?.toLowerCase()

  if (normalizedType === 'boolean') {
    const boolValue = value === true || value === 1 || value === '1' || value === 'true'
    return (
      <span
        className={`inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-semibold ${
          boolValue ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
        }`}
      >
        {boolValue ? 'Yes' : 'No'}
      </span>
    )
  }

  if (normalizedType === 'rating') {
    if (typeof value === 'string' && Number.isNaN(parseFloat(value))) {
      return (
        <span className="inline-flex items-center px-3 py-1.5 rounded-lg bg-purple-50 text-purple-700 text-sm font-semibold capitalize">
          {value}
        </span>
      )
    }
    const numValue = typeof value === 'number' ? value : parseFloat(String(value))
    if (Number.isNaN(numValue)) return <span className="text-gray-300">—</span>
    const percentage = Math.round(Math.max(0, Math.min(1, numValue)) * 100)
    const barColor =
      percentage >= 80 ? 'bg-emerald-500' : percentage >= 60 ? 'bg-amber-500' : 'bg-rose-500'
    const textColor =
      percentage >= 80 ? 'text-emerald-700' : percentage >= 60 ? 'text-amber-700' : 'text-rose-700'
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-baseline gap-1">
          <span className={`text-2xl font-bold tabular-nums ${textColor}`}>{percentage}</span>
          <span className="text-sm text-gray-400">%</span>
        </div>
        <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${barColor}`} style={{ width: `${percentage}%` }} />
        </div>
      </div>
    )
  }

  if (normalizedType === 'number') {
    const numValue = typeof value === 'number' ? value : parseFloat(String(value))
    if (Number.isNaN(numValue)) return <span className="text-gray-300">—</span>
    return <span className="text-2xl font-bold text-gray-900 tabular-nums">{numValue.toFixed(2)}</span>
  }

  if (normalizedType === 'text') {
    return (
      <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap break-words">
        {String(value)}
      </p>
    )
  }

  if (normalizedType === 'category') {
    return (
      <span className="inline-flex max-w-full items-center px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-semibold whitespace-normal break-words leading-snug">
        {String(value)}
      </span>
    )
  }

  return (
    <span className="block max-w-full text-base font-semibold leading-snug text-gray-900 whitespace-normal break-words">
      {String(value)}
    </span>
  )
}

function MetricTile({
  metricId,
  metric,
  metricNameById,
  draftMetricIds,
  onPromoteDraft,
  accent,
}: {
  metricId: string
  metric: MetricScoreEntry
  metricNameById?: Record<string, string>
  draftMetricIds?: Set<string>
  onPromoteDraft?: (metricId: string) => void
  accent: 'purple' | 'violet' | 'indigo'
}) {
  const name = metric.metric_name || metricNameById?.[metricId] || metricId.slice(0, 8)
  const displayValue = metric.skipped ?? metric.value
  const borderClass =
    accent === 'purple'
      ? 'border-purple-200 bg-purple-50/50'
      : accent === 'violet'
        ? 'border-violet-200 bg-violet-50/50'
        : 'border-indigo-200 bg-indigo-50/50'
  const titleClass =
    accent === 'purple'
      ? 'text-purple-800'
      : accent === 'violet'
        ? 'text-violet-800'
        : 'text-indigo-800'

  return (
    <div className={`min-w-0 rounded-lg border p-4 ${borderClass}`}>
      <div className={`text-xs font-bold uppercase mb-2 leading-snug break-words ${titleClass}`}>
        {name}
      </div>
      <div>{formatMetricValue(displayValue, metric.type, name)}</div>
      {metric.rationale?.trim() && (
        <p className="mt-2 text-xs text-gray-600 leading-relaxed border-t border-gray-100 pt-2">
          {metric.rationale.trim()}
        </p>
      )}
      {draftMetricIds?.has(metricId) && onPromoteDraft && (
        <button
          type="button"
          className="mt-2 text-xs font-medium text-primary-700 hover:text-primary-900"
          onClick={() => onPromoteDraft(metricId)}
        >
          Promote draft metric
        </button>
      )}
    </div>
  )
}

function MetricSection({
  title,
  icon: Icon,
  badge,
  accent,
  entries,
  metricNameById,
  draftMetricIds,
  onPromoteDraft,
}: {
  title: string
  icon: typeof Sparkles
  badge: string
  accent: 'purple' | 'violet' | 'indigo'
  entries: Array<[string, MetricScoreEntry]>
  metricNameById?: Record<string, string>
  draftMetricIds?: Set<string>
  onPromoteDraft?: (metricId: string) => void
}) {
  if (entries.length === 0) return null
  const badgeClass =
    accent === 'purple'
      ? 'bg-purple-100 text-purple-700'
      : accent === 'violet'
        ? 'bg-violet-100 text-violet-700'
        : 'bg-indigo-100 text-indigo-700'
  const titleClass =
    accent === 'purple'
      ? 'text-purple-800'
      : accent === 'violet'
        ? 'text-violet-800'
        : 'text-indigo-800'

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon className={`w-4 h-4 ${titleClass}`} />
        <h3 className={`text-sm font-semibold uppercase tracking-wide ${titleClass}`}>{title}</h3>
        <span className={`px-2 py-0.5 text-xs rounded-full ${badgeClass}`}>{badge}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {entries.map(([metricId, metric]) => (
          <MetricTile
            key={metricId}
            metricId={metricId}
            metric={metric}
            metricNameById={metricNameById}
            draftMetricIds={draftMetricIds}
            onPromoteDraft={onPromoteDraft}
            accent={accent}
          />
        ))}
      </div>
    </div>
  )
}

export default function MetricScoreGrid({
  metricScores,
  metricNameById,
  childMetricIds = new Set<string>(),
  draftMetricIds,
  onPromoteDraft,
}: MetricScoreGridProps) {
  const entries = filterVisibleMetricScores(metricScores, childMetricIds)

  if (entries.length === 0) {
    return <p className="text-sm text-gray-500">No metric scores yet.</p>
  }

  const aiVoice = entries.filter(([, m]) => getCategory(m.metric_name || '') === 'ai_voice')
  const acoustic = entries.filter(([, m]) => getCategory(m.metric_name || '') === 'acoustic')
  const llm = entries.filter(([, m]) => getCategory(m.metric_name || '') === 'llm')

  return (
    <div className="space-y-8">
      <MetricSection
        title="AI Voice Quality"
        icon={Sparkles}
        badge="ML Analysis"
        accent="purple"
        entries={aiVoice}
        metricNameById={metricNameById}
        draftMetricIds={draftMetricIds}
        onPromoteDraft={onPromoteDraft}
      />
      <MetricSection
        title="Acoustic Metrics"
        icon={AudioWaveform}
        badge="Signal Analysis"
        accent="violet"
        entries={acoustic}
        metricNameById={metricNameById}
        draftMetricIds={draftMetricIds}
        onPromoteDraft={onPromoteDraft}
      />
      <MetricSection
        title="LLM Metrics"
        icon={Brain}
        badge="Language Analysis"
        accent="indigo"
        entries={llm}
        metricNameById={metricNameById}
        draftMetricIds={draftMetricIds}
        onPromoteDraft={onPromoteDraft}
      />
    </div>
  )
}
