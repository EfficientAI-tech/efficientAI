import { Trophy, Download, FileText, Loader2, Share2, Lock, Sparkles } from 'lucide-react'
import { useState } from 'react'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { DEFAULT_TTS_REPORT_OPTIONS, TTSComparison, TTSReportJob, TTSReportOptions } from '../types'
import MetricCard from './MetricCard'
import SampleGroup from './SampleGroup'
import StatusBadge from './StatusBadge'
import ReportConfigModal from './ReportConfigModal'
import ShareBlindTestModal from './ShareBlindTestModal'
import ExternalResponsesPanel from './ExternalResponsesPanel'

function hasSecondProvider(comp: {
  provider_b?: string | null
  model_b?: string | null
  samples?: Array<{ side?: string | null; audio_s3_key?: string | null; audio_url?: string | null }>
}): boolean {
  if (comp.provider_b && comp.model_b) return true
  return !!(comp.samples || []).some(
    (s) => s.side === 'B' && (s.audio_s3_key || s.audio_url),
  )
}

function buildVoiceHzMaps(comp: TTSComparison): {
  a: Record<string, number>
  b: Record<string, number>
} {
  const a: Record<string, number> = {}
  const b: Record<string, number> = {}
  for (const v of comp.voices_a || []) {
    if (v.sample_rate_hz) a[v.id] = v.sample_rate_hz
  }
  for (const v of comp.voices_b || []) {
    if (v.sample_rate_hz) b[v.id] = v.sample_rate_hz
  }
  return { a, b }
}

interface CustomMetricSummaryEntry {
  metric_id: string
  metric_name: string
  type?: string
  value: number | string | null
  sample_count?: number
  label_counts?: Record<string, number>
}

function readCustomMetrics(side: any): CustomMetricSummaryEntry[] {
  const list = side?.custom_metrics
  return Array.isArray(list) ? list : []
}

function mergeCustomMetricKeys(
  a: CustomMetricSummaryEntry[],
  b: CustomMetricSummaryEntry[],
): Array<{ metric_id: string; metric_name: string; type?: string }> {
  const map = new Map<string, { metric_id: string; metric_name: string; type?: string }>()
  for (const item of [...a, ...b]) {
    if (!map.has(item.metric_id)) {
      map.set(item.metric_id, {
        metric_id: item.metric_id,
        metric_name: item.metric_name,
        type: item.type,
      })
    }
  }
  return Array.from(map.values())
}

interface ComparisonResultsViewProps {
  comparison: TTSComparison
  playingId: string | null
  onPlay: (id: string, url: string) => void
  isDownloading: boolean
  isCreatingReport: boolean
  reportJob: TTSReportJob | null
  onDownloadPdf: (options?: TTSReportOptions) => void
  onGenerateAsync: (options?: TTSReportOptions) => void
  onOpenAsyncReport: () => void
}

export default function ComparisonResultsView({
  comparison,
  playingId,
  onPlay,
  isDownloading,
  isCreatingReport,
  reportJob,
  onDownloadPdf,
  onGenerateAsync,
  onOpenAsyncReport,
}: ComparisonResultsViewProps) {
  const hzMaps = buildVoiceHzMaps(comparison)
  const [showReportConfig, setShowReportConfig] = useState(false)
  const [showShareModal, setShowShareModal] = useState(false)
  const [lastOptions, setLastOptions] = useState<TTSReportOptions>(DEFAULT_TTS_REPORT_OPTIONS)
  // Audio is ready when generation has finished. Evaluation can still be
  // running in the background, but the user should be able to create and
  // share a blind test as soon as audio clips exist.
  const canShareBlindTest =
    hasSecondProvider(comparison) &&
    (comparison.status === 'evaluating' || comparison.status === 'completed')
  const isBlindTestOnly = (comparison.mode || 'benchmark') === 'blind_test_only'
  const showAutomatedMetrics = !isBlindTestOnly

  const handleDownload = (options: TTSReportOptions) => {
    setLastOptions(options)
    onDownloadPdf(options)
    setShowReportConfig(false)
  }

  const handleGenerateAsync = (options: TTSReportOptions) => {
    setLastOptions(options)
    onGenerateAsync(options)
    setShowReportConfig(false)
  }

  return (
    <div className="space-y-6">
      {/* Summary Header */}
      <div className="bg-white rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              {comparison.simulation_id && (
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs font-mono rounded border border-gray-200">
                  #{comparison.simulation_id}
                </span>
              )}
              {comparison.name}
            </h2>
            <p className="text-sm text-gray-500">
              {isBlindTestOnly ? (
                <>
                  Standalone blind test &middot;{' '}
                  {comparison.sample_texts?.length || 0} pairs &middot;{' '}
                  {comparison.samples?.length || 0} audio files
                </>
              ) : (
                <>
                  {comparison.sample_texts?.length || 0} samples &middot;{' '}
                  {comparison.samples?.length || 0} audio files
                  {comparison.num_runs > 1 && <> &middot; {comparison.num_runs} runs</>}
                </>
              )}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusBadge status={comparison.status} />
            <div className="flex items-center gap-2">
              {canShareBlindTest && (
                <Button
                  variant="outline"
                  size="sm"
                  leftIcon={<Share2 className="w-4 h-4" />}
                  onClick={() => setShowShareModal(true)}
                >
                  {comparison.blind_test_share ? 'Manage Blind Test' : 'Create Blind Test'}
                </Button>
              )}
              {showAutomatedMetrics && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    leftIcon={
                      isDownloading ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )
                    }
                    onClick={() => setShowReportConfig(true)}
                    disabled={comparison.status !== 'completed' || isDownloading}
                  >
                    Download PDF
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    leftIcon={
                      isCreatingReport ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <FileText className="w-4 h-4" />
                      )
                    }
                    onClick={() => setShowReportConfig(true)}
                    disabled={isCreatingReport}
                  >
                    Generate Async
                  </Button>
                  {reportJob?.status === 'completed' && reportJob.download_url && (
                    <Button
                      variant="outline"
                      size="sm"
                      leftIcon={<Download className="w-4 h-4" />}
                      onClick={onOpenAsyncReport}
                    >
                      Open Async PDF
                    </Button>
                  )}
                </>
              )}
            </div>
            {reportJob && reportJob.status !== 'completed' && reportJob.status !== 'failed' && (
              <p className="text-xs text-gray-500">Async report: {reportJob.status}</p>
            )}
            {reportJob?.status === 'failed' && (
              <p className="text-xs text-red-600">
                Async report failed: {reportJob.error_message || 'unknown error'}
              </p>
            )}
          </div>
        </div>

        {comparison.blind_test_share?.creator_notes && (
          <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-start gap-2">
              <Lock className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-amber-900 uppercase tracking-wide mb-1">
                  Internal notes
                  <span className="ml-2 normal-case text-[10px] font-medium text-amber-700">
                    (not shown to raters)
                  </span>
                </p>
                <p className="text-sm text-amber-900 whitespace-pre-line break-words">
                  {comparison.blind_test_share.creator_notes}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Winner Banner */}
        {showAutomatedMetrics &&
          hasSecondProvider(comparison) &&
          comparison.evaluation_summary &&
          (() => {
            const sumA = comparison.evaluation_summary.provider_a || {}
            const sumB = comparison.evaluation_summary.provider_b || {}
            const mosA = sumA['MOS Score'] ?? 0
            const mosB = sumB['MOS Score'] ?? 0
            const winner = mosA >= mosB ? 'A' : 'B'
            const winnerName =
              winner === 'A'
                ? getProviderInfo(comparison.provider_a || '').label
                : getProviderInfo(comparison.provider_b || '').label

            return (
              <div className="p-5 bg-gradient-to-r from-green-500 via-emerald-500 to-teal-500 rounded-xl text-white mb-6">
                <div className="flex items-center justify-center gap-3">
                  <Trophy className="w-8 h-8" />
                  <span className="text-xl font-bold">Recommended: {winnerName}</span>
                </div>
              </div>
            )
          })()}

        {/* Metrics Table */}
        {showAutomatedMetrics &&
          comparison.evaluation_summary &&
          (() => {
            const sumA = comparison.evaluation_summary.provider_a || {}
            const sumB = comparison.evaluation_summary.provider_b || {}
            const hasTwoProviders = hasSecondProvider(comparison)

            const cards: Array<{
              key: string
              label: string
              valueA: any
              valueB: any
              unit?: string
              higherIsBetter: boolean
            }> = [
              { key: 'MOS Score', label: 'MOS Score', valueA: sumA['MOS Score'], valueB: hasTwoProviders ? sumB['MOS Score'] : null, higherIsBetter: true },
              { key: 'Valence', label: 'Valence', valueA: sumA['Valence'], valueB: hasTwoProviders ? sumB['Valence'] : null, higherIsBetter: true },
              { key: 'Arousal', label: 'Arousal', valueA: sumA['Arousal'], valueB: hasTwoProviders ? sumB['Arousal'] : null, higherIsBetter: true },
              { key: 'Prosody Score', label: 'Prosody', valueA: sumA['Prosody Score'], valueB: hasTwoProviders ? sumB['Prosody Score'] : null, higherIsBetter: true },
              { key: 'avg_ttfb_ms', label: 'TTFB', valueA: sumA['avg_ttfb_ms'], valueB: hasTwoProviders ? sumB['avg_ttfb_ms'] : null, unit: 'ms', higherIsBetter: false },
              { key: 'avg_latency_ms', label: 'Total Latency', valueA: sumA['avg_latency_ms'], valueB: hasTwoProviders ? sumB['avg_latency_ms'] : null, unit: 'ms', higherIsBetter: false },
              { key: 'WER', label: 'WER', valueA: sumA['WER'], valueB: hasTwoProviders ? sumB['WER'] : null, higherIsBetter: false },
              { key: 'CER', label: 'CER', valueA: sumA['CER'], valueB: hasTwoProviders ? sumB['CER'] : null, higherIsBetter: false },
            ].filter((c) => c.valueA != null || c.valueB != null)

            if (cards.length === 0) return null

            return (
              <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3 mb-6">
                {cards.map((c) => (
                  <MetricCard
                    key={c.key}
                    label={c.label}
                    valueA={c.valueA}
                    valueB={c.valueB}
                    unit={c.unit}
                    higherIsBetter={c.higherIsBetter}
                  />
                ))}
              </div>
            )
          })()}

        {/* Custom LLM-judged metrics */}
        {showAutomatedMetrics &&
          comparison.evaluation_summary &&
          (() => {
            const sumA = comparison.evaluation_summary.provider_a || {}
            const sumB = comparison.evaluation_summary.provider_b || {}
            const hasTwoProviders = hasSecondProvider(comparison)
            const customA = readCustomMetrics(sumA)
            const customB = readCustomMetrics(sumB)
            const merged = mergeCustomMetricKeys(customA, customB)
            if (merged.length === 0) return null

            const lookupA = new Map(customA.map((m) => [m.metric_id, m]))
            const lookupB = new Map(customB.map((m) => [m.metric_id, m]))

            return (
              <div className="mb-6">
                <div className="flex items-center gap-2 mb-2 text-xs font-semibold text-purple-700 uppercase tracking-wide">
                  <Sparkles className="w-3.5 h-3.5" />
                  Custom Metrics (LLM judge)
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
                  {merged.map((m) => {
                    const a = lookupA.get(m.metric_id)
                    const b = lookupB.get(m.metric_id)
                    const valueAIsNumeric = typeof a?.value === 'number'
                    const valueBIsNumeric = typeof b?.value === 'number'

                    if (valueAIsNumeric || valueBIsNumeric) {
                      return (
                        <MetricCard
                          key={m.metric_id}
                          label={m.metric_name}
                          valueA={valueAIsNumeric ? (a!.value as number) : null}
                          valueB={
                            hasTwoProviders && valueBIsNumeric ? (b!.value as number) : null
                          }
                          higherIsBetter
                        />
                      )
                    }

                    const aLabel = a?.value != null ? String(a.value) : '—'
                    const bLabel = b?.value != null ? String(b.value) : '—'
                    return (
                      <div
                        key={m.metric_id}
                        className="min-w-0 overflow-hidden bg-white rounded-lg p-4 border border-gray-100 shadow-sm"
                      >
                        <p className="text-xs text-gray-500 mb-2 font-medium truncate">
                          {m.metric_name}
                        </p>
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 min-w-0">
                          <span className="min-w-0 truncate text-sm leading-tight font-semibold text-gray-700" title={aLabel}>
                            {aLabel}
                          </span>
                          {hasTwoProviders && (
                            <>
                              <span className="text-xs text-gray-400">vs</span>
                              <span className="min-w-0 truncate text-sm leading-tight font-semibold text-gray-700" title={bLabel}>
                                {bLabel}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })()}

        {/* Provider Labels */}
        <div className="flex items-center justify-center gap-6 mb-4">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">
              A
            </span>
            <ProviderLogo provider={comparison.provider_a || ''} size="sm" />
            <span className="text-sm font-medium text-gray-700">
              {getProviderInfo(comparison.provider_a || '').label}
              {comparison.model_a ? ` (${comparison.model_a})` : ''}
            </span>
          </div>
          {hasSecondProvider(comparison) && (
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center text-xs font-bold">
                B
              </span>
              <ProviderLogo provider={comparison.provider_b || ''} size="sm" />
              <span className="text-sm font-medium text-gray-700">
                {getProviderInfo(comparison.provider_b || '').label}
                {comparison.model_b ? ` (${comparison.model_b})` : ''}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Per-Sample Details */}
      <div className="bg-white rounded-xl shadow-lg p-6">
        <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <FileText className="w-5 h-5 text-gray-600" />
          Audio Samples
        </h3>
        <div className="space-y-3 max-h-[700px] overflow-y-auto">
          {comparison.sample_texts?.map((text, idx) => (
            <SampleGroup
              key={idx}
              sampleIndex={idx}
              text={text}
              samples={comparison.samples.filter((s) => s.sample_index === idx)}
              providerA={comparison.provider_a || ''}
              providerB={comparison.provider_b || undefined}
              playingId={playingId}
              onPlay={onPlay}
              numRuns={comparison.num_runs || 1}
              hzMapA={hzMaps.a}
              hzMapB={hzMaps.b}
            />
          ))}
        </div>
      </div>

      {canShareBlindTest && <ExternalResponsesPanel comparison={comparison} />}

      <ReportConfigModal
        isOpen={showReportConfig}
        initialOptions={lastOptions}
        isDownloading={isDownloading}
        isCreatingReport={isCreatingReport}
        onClose={() => setShowReportConfig(false)}
        onDownloadPdf={handleDownload}
        onGenerateAsync={handleGenerateAsync}
      />

      {canShareBlindTest && (
        <ShareBlindTestModal
          isOpen={showShareModal}
          comparisonId={comparison.id}
          defaultTitle={
            comparison.name ||
            `Voice Blind Test${comparison.simulation_id ? ` #${comparison.simulation_id}` : ''}`
          }
          onClose={() => setShowShareModal(false)}
        />
      )}
    </div>
  )
}
