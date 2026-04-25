import { Trophy, Download, FileText, Loader2, Share2 } from 'lucide-react'
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
}): boolean {
  return !!(comp.provider_b && comp.model_b)
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
              {comparison.sample_texts?.length || 0} samples &middot;{' '}
              {comparison.samples?.length || 0} audio files
              {comparison.num_runs > 1 && <> &middot; {comparison.num_runs} runs</>}
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

        {/* Winner Banner */}
        {hasSecondProvider(comparison) &&
          comparison.evaluation_summary &&
          (() => {
            const sumA = comparison.evaluation_summary.provider_a || {}
            const sumB = comparison.evaluation_summary.provider_b || {}
            const mosA = sumA['MOS Score'] ?? 0
            const mosB = sumB['MOS Score'] ?? 0
            const winner = mosA >= mosB ? 'A' : 'B'
            const winnerName =
              winner === 'A'
                ? getProviderInfo(comparison.provider_a).label
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
        {comparison.evaluation_summary &&
          (() => {
            const sumA = comparison.evaluation_summary.provider_a || {}
            const sumB = comparison.evaluation_summary.provider_b || {}
            const hasTwoProviders = hasSecondProvider(comparison)
            return (
              <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3 mb-6">
                <MetricCard
                  label="MOS Score"
                  valueA={sumA['MOS Score']}
                  valueB={hasTwoProviders ? sumB['MOS Score'] : null}
                  higherIsBetter
                />
                <MetricCard
                  label="Valence"
                  valueA={sumA['Valence']}
                  valueB={hasTwoProviders ? sumB['Valence'] : null}
                  higherIsBetter
                />
                <MetricCard
                  label="Arousal"
                  valueA={sumA['Arousal']}
                  valueB={hasTwoProviders ? sumB['Arousal'] : null}
                  higherIsBetter
                />
                <MetricCard
                  label="Prosody"
                  valueA={sumA['Prosody Score']}
                  valueB={hasTwoProviders ? sumB['Prosody Score'] : null}
                  higherIsBetter
                />
                <MetricCard
                  label="TTFB"
                  valueA={sumA['avg_ttfb_ms']}
                  valueB={hasTwoProviders ? sumB['avg_ttfb_ms'] : null}
                  unit="ms"
                  higherIsBetter={false}
                />
                <MetricCard
                  label="Total Latency"
                  valueA={sumA['avg_latency_ms']}
                  valueB={hasTwoProviders ? sumB['avg_latency_ms'] : null}
                  unit="ms"
                  higherIsBetter={false}
                />
                <MetricCard
                  label="WER"
                  valueA={sumA['WER']}
                  valueB={hasTwoProviders ? sumB['WER'] : null}
                  higherIsBetter={false}
                />
                <MetricCard
                  label="CER"
                  valueA={sumA['CER']}
                  valueB={hasTwoProviders ? sumB['CER'] : null}
                  higherIsBetter={false}
                />
              </div>
            )
          })()}

        {/* Provider Labels */}
        <div className="flex items-center justify-center gap-6 mb-4">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">
              A
            </span>
            <ProviderLogo provider={comparison.provider_a} size="sm" />
            <span className="text-sm font-medium text-gray-700">
              {getProviderInfo(comparison.provider_a).label} ({comparison.model_a})
            </span>
          </div>
          {hasSecondProvider(comparison) && (
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center text-xs font-bold">
                B
              </span>
              <ProviderLogo provider={comparison.provider_b || ''} size="sm" />
              <span className="text-sm font-medium text-gray-700">
                {getProviderInfo(comparison.provider_b || '').label} ({comparison.model_b})
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
              providerA={comparison.provider_a}
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
