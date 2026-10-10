import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  Calendar,
  CheckCircle2,
  Loader2,
  Radio,
  Sparkles,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import { getApiErrorMessage } from '../../../lib/apiErrors'
import {
  getIntegrationPlatformLabel,
  getIntegrationPlatformLogo,
} from '../../../config/providers'
import { IntegrationPlatform } from '../../../types/api'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'
import PlatformImportWindowPicker, {
  toDatetimeLocalValue,
} from './PlatformImportWindowPicker'
import { usePinPlatformImport } from './PlatformImportProgressDock'

type Props = {
  open: boolean
  onClose: () => void
  onImportStarted?: () => void
}

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

type PlatformKey = 'elevenlabs' | 'vapi' | 'retell'
type Step = 'provider' | 'configure' | 'preview' | 'starting' | 'started'

const PLATFORMS: Array<{
  id: PlatformKey
  platform: IntegrationPlatform
  blurb: string
}> = [
  {
    id: 'elevenlabs',
    platform: IntegrationPlatform.ELEVENLABS,
    blurb: 'ConvAI conversations and recordings',
  },
  {
    id: 'vapi',
    platform: IntegrationPlatform.VAPI,
    blurb: 'Assistant calls with stereo recordings',
  },
  {
    id: 'retell',
    platform: IntegrationPlatform.RETELL,
    blurb: 'Voice agent call history',
  },
]

const RANGE_PRESETS = [
  { id: '7d', label: 'Last 7 days', days: 7 },
  { id: '30d', label: 'Last 30 days', days: 30 },
  { id: '90d', label: 'Last 90 days', days: 90 },
] as const

function parseLocalDatetime(value: string): Date {
  return new Date(value)
}

function formatRangeLabel(start: string, end: string): string {
  if (!start || !end) return ''
  const s = parseLocalDatetime(start)
  const e = parseLocalDatetime(end)
  return `${s.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })} → ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`
}

export default function ImportPlatformModal({ open, onClose, onImportStarted }: Props) {
  const navigate = useNavigate()
  const { showToast, ToastContainer } = useToast()
  const pinPlatformImport = usePinPlatformImport()
  const [step, setStep] = useState<Step>('provider')
  const [platform, setPlatform] = useState<PlatformKey | ''>('')
  const [integrationId, setIntegrationId] = useState('')
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [preset, setPreset] = useState<string>('30d')
  const [dataset, setDataset] = useState('')
  const [importProviderTranscript, setImportProviderTranscript] = useState(true)
  const [preview, setPreview] = useState<{
    recordings_in_window: number
    recordings_count_complete: boolean
    count_pages_scanned?: number
    discovery_slices?: number
    sample_count: number
    samples: Array<{ conversation_id: string; started_at?: string | null; status?: string | null }>
  } | null>(null)
  const [startedImportId, setStartedImportId] = useState<string | null>(null)

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
    enabled: open,
  })

  const credentialsForPlatform = useMemo(
    () =>
      integrations.filter(
        (i) => (i.platform || '').toLowerCase() === platform && i.is_active,
      ),
    [integrations, platform],
  )

  const platformMeta = PLATFORMS.find((p) => p.id === platform)

  useEffect(() => {
    if (!open) return
    setStep('provider')
    setPlatform('')
    setIntegrationId('')
    setDataset('')
    setPreview(null)
    setStartedImportId(null)
    const end = new Date()
    end.setMinutes(end.getMinutes() - 15)
    const start = new Date(end)
    start.setDate(start.getDate() - 30)
    setWindowStart(toDatetimeLocalValue(start))
    setWindowEnd(toDatetimeLocalValue(end))
    setPreset('30d')
    setImportProviderTranscript(true)
  }, [open])

  const applyPreset = (presetId: string, days: number) => {
    const end = new Date()
    end.setMinutes(end.getMinutes() - 15)
    const start = new Date(end)
    start.setDate(start.getDate() - days)
    setPreset(presetId)
    setWindowStart(toDatetimeLocalValue(start))
    setWindowEnd(toDatetimeLocalValue(end))
  }

  const platformFilters = useMemo(
    () => ({
      import_provider_transcript: importProviderTranscript,
    }),
    [importProviderTranscript],
  )

  const previewMutation = useMutation({
    mutationFn: () =>
      apiClient.previewPlatformCallImport({
        voice_integration_id: integrationId,
        window_start: parseLocalDatetime(windowStart).toISOString(),
        window_end: parseLocalDatetime(windowEnd).toISOString(),
        filters: platformFilters,
      }),
    onSuccess: (data) => {
      setPreview(data)
      setStep('preview')
    },
    onError: (err: unknown) => {
      showToast(getApiErrorMessage(err, 'Could not preview this window'), 'error')
    },
  })

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createPlatformCallImport({
        voice_integration_id: integrationId,
        window_start: parseLocalDatetime(windowStart).toISOString(),
        window_end: parseLocalDatetime(windowEnd).toISOString(),
        dataset: dataset || undefined,
        filters: platformFilters,
      }),
    onSuccess: (result) => {
      setStartedImportId(result.id)
      setStep('started')
      const label =
        dataset.trim() ||
        `${platformMeta?.platform ? getIntegrationPlatformLabel(platformMeta.platform) : 'Platform'} import`
      pinPlatformImport(result.id, label)
      onImportStarted?.()
    },
    onError: (err: unknown) => {
      setStep('preview')
      showToast(getApiErrorMessage(err, 'Failed to start import'), 'error')
    },
  })

  const canConfigure =
    platform && integrationId && windowStart && windowEnd && windowEnd > windowStart

  if (!open) return null

  return renderModal(
    <div className="fixed inset-0 z-[200] flex items-start justify-center overflow-y-auto bg-black/50 p-4 py-6 sm:py-10">
      <ToastContainer />
      <div
        className="relative my-auto flex w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        role="dialog"
        aria-labelledby="platform-import-title"
      >
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 id="platform-import-title" className="text-lg font-semibold text-gray-900">
              Import historical calls
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Pull recordings and transcripts from your voice platform into Imports.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-3 bg-gray-50 border-b border-gray-100 flex gap-2 text-xs font-medium">
          {(['provider', 'configure', 'preview', 'started'] as const).map((s, i) => {
            const labels = ['Platform', 'Window', 'Review', 'Started']
            const active =
              step === s ||
              (step === 'starting' && s === 'preview') ||
              (step === 'started' && s === 'started')
            const done =
              (s === 'provider' && step !== 'provider') ||
              (s === 'configure' && (step === 'preview' || step === 'starting' || step === 'started')) ||
              (s === 'preview' && step === 'started')
            return (
              <div key={s} className="flex items-center gap-2 flex-1 min-w-0">
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                    done
                      ? 'bg-primary-600 text-white'
                      : active
                        ? 'bg-primary-100 text-primary-700 ring-2 ring-primary-500'
                        : 'bg-white text-gray-400 border border-gray-200'
                  }`}
                >
                  {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : i + 1}
                </span>
                <span className={active || done ? 'text-gray-900' : 'text-gray-400'}>
                  {labels[i]}
                </span>
                {i < 3 && <ArrowRight className="h-3 w-3 text-gray-300 ml-auto hidden sm:block" />}
              </div>
            )
          })}
        </div>

        <div className="max-h-[calc(90vh-12.5rem)] overflow-y-auto px-6 py-5 space-y-5">
          {step === 'provider' && (
            <>
              <p className="text-sm text-gray-600">Which platform are you importing from?</p>
              <div className="grid sm:grid-cols-3 gap-3">
                {PLATFORMS.map((p) => {
                  const logo = getIntegrationPlatformLogo(p.platform)
                  const selected = platform === p.id
                  const count = integrations.filter(
                    (i) => (i.platform || '').toLowerCase() === p.id && i.is_active,
                  ).length
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => {
                        setPlatform(p.id)
                        setIntegrationId('')
                        setStep('configure')
                      }}
                      className={`text-left rounded-lg border-2 p-4 transition-all ${
                        selected
                          ? 'border-primary-500 bg-primary-50/50 shadow-sm'
                          : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      {logo ? (
                        <img src={logo} alt="" className="h-8 w-8 object-contain mb-2" />
                      ) : (
                        <Radio className="h-8 w-8 text-gray-400 mb-2" />
                      )}
                      <div className="font-medium text-gray-900 text-sm">
                        {getIntegrationPlatformLabel(p.platform)}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">{p.blurb}</div>
                      <div className="text-xs text-gray-400 mt-2">
                        {count > 0 ? `${count} credential${count === 1 ? '' : 's'}` : 'No credentials'}
                      </div>
                    </button>
                  )
                })}
              </div>
            </>
          )}

          {step === 'configure' && platformMeta && (
            <>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-primary-50 border border-primary-100">
                {getIntegrationPlatformLogo(platformMeta.platform) && (
                  <img
                    src={getIntegrationPlatformLogo(platformMeta.platform)!}
                    alt=""
                    className="h-10 w-10 object-contain"
                  />
                )}
                <div>
                  <div className="font-medium text-gray-900">
                    {getIntegrationPlatformLabel(platformMeta.platform)}
                  </div>
                  <button
                    type="button"
                    className="text-xs text-primary-600 hover:underline"
                    onClick={() => setStep('provider')}
                  >
                    Change platform
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  API credential
                </label>
                {credentialsForPlatform.length === 0 ? (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                    No active {getIntegrationPlatformLabel(platformMeta.platform)} credentials.
                    <Link
                      to="/integrations"
                      className="block mt-2 font-medium text-primary-600 hover:underline"
                      onClick={onClose}
                    >
                      Add integration in Settings →
                    </Link>
                  </div>
                ) : (
                  <select
                    className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                    value={integrationId}
                    onChange={(e) => setIntegrationId(e.target.value)}
                  >
                    <option value="">Select credential</option>
                    {credentialsForPlatform.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name || 'Default'} {i.is_default ? '(default)' : ''}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
                    <Calendar className="h-4 w-4 text-gray-400" />
                    Call time range
                  </label>
                  <span className="text-xs text-gray-500">End capped ~15 min before now</span>
                </div>
                <PlatformImportWindowPicker
                  windowStart={windowStart}
                  windowEnd={windowEnd}
                  activePreset={preset}
                  presets={RANGE_PRESETS}
                  onPreset={applyPreset}
                  onRangeChange={(start, end) => {
                    setPreset('')
                    setWindowStart(start)
                    setWindowEnd(end)
                  }}
                  formatRangeLabel={formatRangeLabel}
                />
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50/80 p-3 space-y-2">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    checked={importProviderTranscript}
                    onChange={(e) => setImportProviderTranscript(e.target.checked)}
                  />
                  <span className="min-w-0">
                    <span className="text-sm font-medium text-gray-900">
                      Import production transcript from platform
                    </span>
                    <span className="block text-xs text-gray-600 mt-0.5">
                      {platform === 'elevenlabs'
                        ? 'Fetches ElevenLabs ConvAI turns into the production transcript (and speaker turns when available) alongside the recording. Use Evaluate → Production transcript — same flow as CSV imports with a transcript column.'
                        : 'Stores the provider call transcript on each row with the recording so you can run evaluations on the production transcript without re-diarising.'}
                    </span>
                  </span>
                </label>
              </div>

              <label className="block text-sm">
                <span className="font-medium text-gray-700">Dataset label (optional)</span>
                <input
                  className="mt-1.5 w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                  placeholder="e.g. Q4 production calls"
                  value={dataset}
                  onChange={(e) => setDataset(e.target.value)}
                />
              </label>
            </>
          )}

          {(step === 'preview' || step === 'starting') && platformMeta && preview && (
            <>
              <div className="rounded-lg border border-gray-200 overflow-hidden">
                <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
                  <div className="text-sm font-medium text-gray-900">Preview</div>
                </div>
                <div className="p-4 space-y-4">
                  <div className="rounded-lg bg-primary-50 p-4 text-center">
                    <div className="text-3xl font-bold text-primary-700 tabular-nums">
                      {preview.recordings_count_complete
                        ? preview.recordings_in_window.toLocaleString()
                        : `${preview.recordings_in_window.toLocaleString()}+`}
                    </div>
                    <div className="text-sm text-primary-900/90 mt-1 font-medium">
                      recordings in this window
                    </div>
                    <p className="text-xs text-primary-800/70 mt-2 max-w-md mx-auto">
                      {preview.recordings_count_complete
                        ? 'Counted from your provider for the selected dates.'
                        : `At least this many (preview scanned ${preview.count_pages_scanned ?? '?'} API pages; full import may find more).`}
                      {preview.discovery_slices != null && preview.discovery_slices > 0
                        ? ` Import runs in ${preview.discovery_slices} daily discovery windows.`
                        : ''}
                    </p>
                  </div>
                  {preview.samples.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-2 px-1">
                        Recent examples ({preview.samples.length})
                      </div>
                      <ul className="rounded-lg border border-gray-100 divide-y divide-gray-100">
                        {preview.samples.map((s) => (
                          <li
                            key={s.conversation_id}
                            className="px-3 py-2 text-xs flex justify-between gap-2"
                          >
                            <span className="font-mono text-gray-700 truncate">{s.conversation_id}</span>
                            <span className="text-gray-400 shrink-0">
                              {s.started_at
                                ? new Date(s.started_at).toLocaleDateString()
                                : s.status || '—'}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
              <p className="text-xs text-gray-500">
                You can close this dialog after starting — live progress is on the import detail page.
              </p>
            </>
          )}

          {step === 'started' && startedImportId && (
            <div className="text-center py-4 space-y-4">
              <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-green-100">
                <Sparkles className="h-7 w-7 text-green-600" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Import is running</h3>
                <p className="text-sm text-gray-600 mt-1 max-w-md mx-auto">
                  We are listing calls in your time window, then fetching each recording. This runs
                  in the background so evaluations and other imports are not blocked.
                </p>
              </div>
              <p className="text-xs text-gray-500">
                Total runtime depends on how many calls are in the window — not just the preview count.
              </p>
              <div className="flex flex-col sm:flex-row gap-2 justify-center pt-2">
                <Button
                  variant="primary"
                  onClick={() => {
                    onClose()
                    navigate(`/call-imports/${startedImportId}`)
                  }}
                >
                  View live progress
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    onClose()
                  }}
                >
                  Keep working — status panel stays open
                </Button>
              </div>
            </div>
          )}
        </div>

        {step !== 'started' && (
          <div className="px-6 py-4 border-t border-gray-100 flex justify-between gap-3 bg-gray-50/80">
            <Button
              variant="ghost"
              onClick={() => {
                if (step === 'configure') setStep('provider')
                else if (step === 'preview') setStep('configure')
                else onClose()
              }}
            >
              {step === 'provider' ? 'Cancel' : 'Back'}
            </Button>
            {step === 'configure' && (
              <Button
                variant="primary"
                disabled={!canConfigure}
                isLoading={previewMutation.isPending}
                onClick={() => previewMutation.mutate()}
              >
                Preview calls in window
              </Button>
            )}
            {step === 'preview' && (
              <Button
                variant="primary"
                isLoading={createMutation.isPending}
                onClick={() => {
                  setStep('starting')
                  createMutation.mutate()
                }}
              >
                Confirm & start import
              </Button>
            )}
          </div>
        )}

        {step === 'starting' && (
          <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        )}
      </div>
    </div>,
  )
}
