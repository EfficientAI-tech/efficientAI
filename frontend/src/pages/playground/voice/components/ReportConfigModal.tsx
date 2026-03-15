import { useEffect, useState, type ReactNode } from 'react'
import { Loader2, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import Button from '../../../../components/Button'
import { apiClient } from '../../../../lib/api'
import {
  DEFAULT_TTS_REPORT_OPTIONS,
  TTSReportOptions,
  TTSZoneThresholdOverrides,
} from '../types'

interface ReportConfigModalProps {
  isOpen: boolean
  initialOptions?: TTSReportOptions
  isDownloading: boolean
  isCreatingReport: boolean
  onClose: () => void
  onDownloadPdf: (options: TTSReportOptions) => void
  onGenerateAsync: (options: TTSReportOptions) => void
}

type BooleanOptionKey = {
  [K in keyof TTSReportOptions]: TTSReportOptions[K] extends boolean ? K : never
}[keyof TTSReportOptions]

type ThresholdMetricKey = keyof TTSZoneThresholdOverrides
type ThresholdFieldKey = 'good_min' | 'neutral_min' | 'good_max' | 'neutral_max'

const THRESHOLD_CONFIGS: Array<{
  key: ThresholdMetricKey
  label: string
  firstField: ThresholdFieldKey
  firstLabel: string
  secondField: ThresholdFieldKey
  secondLabel: string
  step?: string
}> = [
  {
    key: 'avg_mos',
    label: 'MOS',
    firstField: 'neutral_min',
    firstLabel: 'Neutral starts',
    secondField: 'good_min',
    secondLabel: 'Good starts',
    step: '0.01',
  },
  {
    key: 'avg_prosody',
    label: 'Prosody',
    firstField: 'neutral_min',
    firstLabel: 'Neutral starts',
    secondField: 'good_min',
    secondLabel: 'Good starts',
    step: '0.01',
  },
  {
    key: 'avg_valence',
    label: 'Valence',
    firstField: 'neutral_min',
    firstLabel: 'Neutral starts',
    secondField: 'good_min',
    secondLabel: 'Good starts',
    step: '0.01',
  },
  {
    key: 'avg_arousal',
    label: 'Arousal',
    firstField: 'neutral_min',
    firstLabel: 'Neutral starts',
    secondField: 'good_min',
    secondLabel: 'Good starts',
    step: '0.01',
  },
  {
    key: 'avg_wer',
    label: 'WER',
    firstField: 'good_max',
    firstLabel: 'Good max',
    secondField: 'neutral_max',
    secondLabel: 'Neutral max',
    step: '0.001',
  },
  {
    key: 'avg_cer',
    label: 'CER',
    firstField: 'good_max',
    firstLabel: 'Good max',
    secondField: 'neutral_max',
    secondLabel: 'Neutral max',
    step: '0.001',
  },
  {
    key: 'avg_ttfb_ms',
    label: 'TTFB (ms)',
    firstField: 'good_max',
    firstLabel: 'Good max',
    secondField: 'neutral_max',
    secondLabel: 'Neutral max',
    step: '1',
  },
  {
    key: 'avg_latency_ms',
    label: 'Latency (ms)',
    firstField: 'good_max',
    firstLabel: 'Good max',
    secondField: 'neutral_max',
    secondLabel: 'Neutral max',
    step: '1',
  },
]

export default function ReportConfigModal({
  isOpen,
  initialOptions,
  isDownloading,
  isCreatingReport,
  onClose,
  onDownloadPdf,
  onGenerateAsync,
}: ReportConfigModalProps) {
  const [options, setOptions] = useState<TTSReportOptions>(initialOptions || DEFAULT_TTS_REPORT_OPTIONS)
  const [showAdvancedThresholds, setShowAdvancedThresholds] = useState(false)
  const [isLoadingOrgDefaults, setIsLoadingOrgDefaults] = useState(false)
  const [isSavingOrgDefaults, setIsSavingOrgDefaults] = useState(false)
  const [orgDefaultsMessage, setOrgDefaultsMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setOptions(initialOptions || DEFAULT_TTS_REPORT_OPTIONS)
    setShowAdvancedThresholds(false)
    setOrgDefaultsMessage(null)
  }, [isOpen, initialOptions])

  useEffect(() => {
    if (!isOpen) return
    let cancelled = false
    ;(async () => {
      setIsLoadingOrgDefaults(true)
      try {
        const res = await apiClient.getVoicePlaygroundReportThresholdDefaults()
        if (cancelled) return
        setOptions((prev) => ({
          ...prev,
          zone_threshold_overrides: (res.zone_threshold_overrides ||
            DEFAULT_TTS_REPORT_OPTIONS.zone_threshold_overrides) as TTSZoneThresholdOverrides,
        }))
      } catch (_err) {
        if (!cancelled) {
          setOrgDefaultsMessage('Could not load org threshold defaults. Using local defaults.')
        }
      } finally {
        if (!cancelled) setIsLoadingOrgDefaults(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [isOpen])

  if (!isOpen) return null

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  const toggle = (key: BooleanOptionKey) => {
    setOptions((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const updateThreshold = (metricKey: ThresholdMetricKey, fieldKey: ThresholdFieldKey, rawValue: string) => {
    const cleanedValue = rawValue.trim()
    const parsed = cleanedValue === '' ? undefined : Number(cleanedValue)
    setOptions((prev) => ({
      ...prev,
      zone_threshold_overrides: {
        ...(prev.zone_threshold_overrides || {}),
        [metricKey]: {
          ...(prev.zone_threshold_overrides?.[metricKey] || {}),
          [fieldKey]: Number.isFinite(parsed as number) ? (parsed as number) : undefined,
        },
      },
    }))
  }

  const resetThresholdsToDefaults = () => {
    setOptions((prev) => ({
      ...prev,
      zone_threshold_overrides: JSON.parse(
        JSON.stringify(DEFAULT_TTS_REPORT_OPTIONS.zone_threshold_overrides)
      ) as TTSZoneThresholdOverrides,
    }))
    setOrgDefaultsMessage('Thresholds reset to system defaults locally.')
  }

  const saveThresholdsAsOrgDefaults = async () => {
    setIsSavingOrgDefaults(true)
    setOrgDefaultsMessage(null)
    try {
      await apiClient.updateVoicePlaygroundReportThresholdDefaults({
        zone_threshold_overrides: options.zone_threshold_overrides as Record<string, {
          good_min?: number
          neutral_min?: number
          good_max?: number
          neutral_max?: number
        }>,
      })
      setOrgDefaultsMessage('Saved threshold defaults for this organization.')
    } catch (_err) {
      setOrgDefaultsMessage('Failed to save org threshold defaults.')
    } finally {
      setIsSavingOrgDefaults(false)
    }
  }

  return renderModal(
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999] p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Customize Report Generation</h3>
            <p className="mt-1 text-sm text-gray-500">
              Configure which metrics and sections should be included in the PDF.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close report configuration modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 px-6 py-5">
          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-semibold text-gray-900">Run Count Display</h4>
            <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={options.show_runs}
                onChange={() => toggle('show_runs')}
                className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              Show run count summary
            </label>
            <div className="mt-3">
              <label className="text-xs font-medium text-gray-600">
                Minimum runs required before showing run count
              </label>
              <input
                type="number"
                min={0}
                max={1000}
                value={options.min_runs_to_show}
                disabled={!options.show_runs}
                onChange={(e) =>
                  setOptions((prev) => ({
                    ...prev,
                    min_runs_to_show: Math.max(0, Number(e.target.value || 0)),
                  }))
                }
                className="mt-1 w-40 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:bg-gray-100 disabled:text-gray-400"
              />
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-semibold text-gray-900">Performance Metrics</h4>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_latency} onChange={() => toggle('include_latency')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Total latency
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_ttfb} onChange={() => toggle('include_ttfb')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                TTFB
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_endpoint} onChange={() => toggle('include_endpoint')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Endpoint type
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-semibold text-gray-900">Quality Metrics (default ON)</h4>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_naturalness} onChange={() => toggle('include_naturalness')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Naturalness (MOS)
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_hallucination} onChange={() => toggle('include_hallucination')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Hallucination section
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_prosody} onChange={() => toggle('include_prosody')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Prosody
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_arousal} onChange={() => toggle('include_arousal')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Arousal
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_valence} onChange={() => toggle('include_valence')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                Valence
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_wer} onChange={() => toggle('include_wer')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                WER
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={options.include_cer} onChange={() => toggle('include_cer')} className="rounded border-gray-300 text-primary-600 focus:ring-primary-500" />
                CER
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-semibold text-gray-900">Hallucination Examples</h4>
            <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={options.include_hallucination_examples}
                onChange={() => toggle('include_hallucination_examples')}
                className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              Include example transcripts in report
            </label>
            <div className="mt-3">
              <label className="text-xs font-medium text-gray-600">Max examples to include</label>
              <input
                type="number"
                min={0}
                max={50}
                value={options.hallucination_examples_limit}
                disabled={!options.include_hallucination_examples}
                onChange={(e) =>
                  setOptions((prev) => ({
                    ...prev,
                    hallucination_examples_limit: Math.max(0, Math.min(50, Number(e.target.value || 0))),
                  }))
                }
                className="mt-1 w-32 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:bg-gray-100 disabled:text-gray-400"
              />
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-semibold text-gray-900">Report Sections</h4>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={options.include_disclaimer_sections}
                  onChange={() => toggle('include_disclaimer_sections')}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                Include disclaimers in PDF
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <button
              type="button"
              className="flex w-full items-center justify-between text-left"
              onClick={() => setShowAdvancedThresholds((prev) => !prev)}
            >
              <h4 className="text-sm font-semibold text-gray-900">Advanced Thresholds</h4>
              <span className="text-xs text-gray-500">
                {showAdvancedThresholds ? 'Hide' : 'Show'}
              </span>
            </button>
            <p className="mt-1 text-xs text-gray-500">
              Tune red / neutral / green cutoffs used by metric ranking bars and legends.
            </p>
            {showAdvancedThresholds && (
              <div className="mt-4 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={resetThresholdsToDefaults}
                  >
                    Reset thresholds to defaults
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={saveThresholdsAsOrgDefaults}
                    disabled={isSavingOrgDefaults}
                    leftIcon={isSavingOrgDefaults ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined}
                  >
                    Save thresholds as org default
                  </Button>
                  {isLoadingOrgDefaults && (
                    <span className="text-xs text-gray-500">Loading org defaults...</span>
                  )}
                </div>
                {orgDefaultsMessage && (
                  <div className="text-xs text-gray-600">{orgDefaultsMessage}</div>
                )}
                {THRESHOLD_CONFIGS.map((cfg) => {
                  const values = options.zone_threshold_overrides?.[cfg.key] || {}
                  const firstValue = values[cfg.firstField]
                  const secondValue = values[cfg.secondField]
                  return (
                    <div
                      key={cfg.key}
                      className="grid grid-cols-1 gap-3 rounded-md border border-gray-100 bg-gray-50 p-3 md:grid-cols-3"
                    >
                      <div className="text-sm font-medium text-gray-800">{cfg.label}</div>
                      <label className="text-xs text-gray-600">
                        {cfg.firstLabel}
                        <input
                          type="number"
                          step={cfg.step || '0.01'}
                          value={firstValue ?? ''}
                          onChange={(e) => updateThreshold(cfg.key, cfg.firstField, e.target.value)}
                          className="mt-1 w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        />
                      </label>
                      <label className="text-xs text-gray-600">
                        {cfg.secondLabel}
                        <input
                          type="number"
                          step={cfg.step || '0.01'}
                          value={secondValue ?? ''}
                          onChange={(e) => updateThreshold(cfg.key, cfg.secondField, e.target.value)}
                          className="mt-1 w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        />
                      </label>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="rounded-md bg-amber-50 p-3 text-xs text-amber-800">
            Legacy explanatory sections remain excluded from PDF. Disclaimers are enabled by default and can be toggled.
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-3 border-t border-gray-200 px-6 py-4">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="ghost"
            onClick={() => onGenerateAsync(options)}
            disabled={isCreatingReport}
          >
            {isCreatingReport ? 'Queuing...' : 'Generate Async'}
          </Button>
          <Button
            variant="primary"
            onClick={() => onDownloadPdf(options)}
            disabled={isDownloading}
          >
            {isDownloading ? 'Downloading...' : 'Download PDF'}
          </Button>
        </div>
      </div>
    </div>
  )
}
