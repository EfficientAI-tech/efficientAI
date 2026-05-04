import { useState, useMemo, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Hash, Play, RotateCcw, Volume2, Plus, ChevronDown, ChevronRight, Mic } from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'
import SampleTextsPanel from './SampleTextsPanel'
import SourcePanel from './SourcePanel'
import ComparisonResultsView from './ComparisonResultsView'
import StatusBadge from './StatusBadge'
import BlindTestOnlyConfig from './BlindTestOnlyConfig'
import ModeChooser from './ModeChooser'

export default function PlaygroundTab() {
  const {
    step,
    providers,
    providersLoading,
    providerA,
    setProviderA,
    modelA,
    setModelA,
    selectedVoicesA,
    setSelectedVoicesA,
    sampleRateA,
    setSampleRateA,
    enableComparison,
    setEnableComparison,
    providerB,
    setProviderB,
    modelB,
    setModelB,
    selectedVoicesB,
    setSelectedVoicesB,
    sampleRateB,
    setSampleRateB,
    numRuns,
    setNumRuns,
    evalSttProvider,
    setEvalSttProvider,
    evalSttModel,
    setEvalSttModel,
    voiceBundles,
    mode,
    sourceTypeA,
    setSourceTypeA,
    sourceTypeB,
    setSourceTypeB,
    callImportRowIdsA,
    setCallImportRowIdsA,
    callImportRowIdsB,
    setCallImportRowIdsB,
    uploadKeysA,
    setUploadKeysA,
    uploadKeysB,
    setUploadKeysB,
    canRun,
    createComparison,
    isCreating,
    comparison,
    progressPct,
    totalSamples,
    completedSamples,
    playingId,
    play,
    resetPlayground,
    activeReportJob,
    isDownloading,
    isCreatingReport,
    downloadReport,
    createReportJob,
    openAsyncReport,
  } = useVoicePlayground()
  const [playbackProfile, setPlaybackProfile] = useState<'default' | 'telephony_narrowband' | 'telephony_wideband'>('default')

  const getTelephonyRateForProvider = (
    provider: string,
    preferredRate: number,
  ): number | null => {
    const providerData = providers.find((p) => p.provider === provider)
    const supportedRates = providerData?.supported_sample_rates || []
    if (supportedRates.length === 0) {
      return null
    }
    if (supportedRates.includes(preferredRate)) {
      return preferredRate
    }
    const fallbackRate = preferredRate === 8000 ? 16000 : 8000
    if (supportedRates.includes(fallbackRate)) {
      return fallbackRate
    }
    return supportedRates[0]
  }

  useEffect(() => {
    if (playbackProfile === 'default') {
      setSampleRateA(null)
      if (enableComparison) {
        setSampleRateB(null)
      }
      return
    }

    const preferredRate = playbackProfile === 'telephony_narrowband' ? 8000 : 16000
    if (providerA) {
      setSampleRateA(getTelephonyRateForProvider(providerA, preferredRate))
    }
    if (enableComparison && providerB) {
      setSampleRateB(getTelephonyRateForProvider(providerB, preferredRate))
    }
  }, [
    playbackProfile,
    providerA,
    providerB,
    enableComparison,
    providers,
    setSampleRateA,
    setSampleRateB,
  ])

  // Configuration step
  if (step === 'configure') {
    if (mode === 'blind_test_only') {
      return (
        <>
          <ModeChooser />
          <BlindTestOnlyConfig />
        </>
      )
    }
    return (
      <>
        <ModeChooser />
        <SampleTextsPanel />

        {/* Number of Runs */}
        <div className="bg-white rounded-xl shadow-sm p-3 border border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Hash className="w-5 h-5 text-gray-500" />
            <div>
              <p className="font-medium text-gray-900 text-sm">Number of Runs</p>
              <p className="text-xs text-gray-500">
                Repeat each voice+text combination. Total evaluations = samples x selected voices x
                runs.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setNumRuns(Math.max(1, numRuns - 1))}
              disabled={numRuns <= 1}
              className="w-7 h-7 rounded-md border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              −
            </button>
            <input
              type="number"
              min={1}
              max={10}
              value={numRuns}
              onChange={(e) => {
                const raw = e.target.value
                if (raw === '') return
                const parsed = Number(raw)
                if (Number.isNaN(parsed)) return
                const clamped = Math.min(10, Math.max(1, parsed))
                setNumRuns(clamped)
              }}
              className="w-14 h-8 text-center font-semibold text-gray-900 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
            <button
              onClick={() => setNumRuns(Math.min(10, numRuns + 1))}
              disabled={numRuns >= 10}
              className="w-7 h-7 rounded-md border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              +
            </button>
          </div>
        </div>

        {/* Playback Profile */}
        <div className="bg-white rounded-xl shadow-sm p-3 border border-gray-100 flex items-center justify-between gap-4">
          <div>
            <p className="font-medium text-gray-900 text-sm">Playback Profile</p>
            <p className="text-xs text-gray-500">
              Simulate how TTS sounds over telephony by forcing lower sample rates.
            </p>
          </div>
          <select
            value={playbackProfile}
            onChange={(e) =>
              setPlaybackProfile(
                e.target.value as 'default' | 'telephony_narrowband' | 'telephony_wideband',
              )
            }
            className="w-60 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
          >
            <option value="default">Studio / Default</option>
            <option value="telephony_narrowband">Telephony (Narrowband 8k)</option>
            <option value="telephony_wideband">Telephony (Wideband 16k)</option>
          </select>
        </div>

        {/* Evaluation STT Settings */}
        <EvalSttPanel
          evalSttProvider={evalSttProvider}
          setEvalSttProvider={setEvalSttProvider}
          evalSttModel={evalSttModel}
          setEvalSttModel={setEvalSttModel}
          voiceBundles={voiceBundles}
        />

        {/* Provider Config Panel */}
        <div className="bg-white rounded-xl shadow-lg p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">Configure Comparison</h2>

          {providersLoading ? (
            <div className="flex items-center justify-center py-12 text-gray-500">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              Loading providers...
            </div>
          ) : providers.length === 0 ? (
            <div className="text-center py-12">
              <Volume2 className="w-12 h-12 mx-auto text-gray-300 mb-3" />
              <p className="text-gray-600 font-medium">No TTS providers configured</p>
              <p className="text-sm text-gray-500 mt-1">Go to Integrations to add API keys for ElevenLabs, Cartesia, OpenAI, Deepgram, or Google.</p>
            </div>
          ) : (
            <>
              <div className="mb-4 flex items-center justify-between gap-3">
                <p className="text-xs text-gray-500">
                  Start with Provider A. Add Provider B only when you want A/B blind testing.
                </p>
                {enableComparison ? (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setEnableComparison(false)
                      setProviderB('')
                      setModelB('')
                      setSelectedVoicesB([])
                      setSampleRateB(null)
                    }}
                  >
                    Remove Provider B
                  </Button>
                ) : (
                  <Button variant="secondary" leftIcon={<Plus className="w-4 h-4" />} onClick={() => setEnableComparison(true)}>
                    Add Provider B
                  </Button>
                )}
              </div>

              <div className={`grid grid-cols-1 ${enableComparison ? 'lg:grid-cols-2' : ''} gap-6 mb-6 relative`}>
                <SourcePanel
                  label="A"
                  color="blue"
                  providers={providers}
                  sourceType={sourceTypeA}
                  onSourceTypeChange={setSourceTypeA}
                  selectedProvider={providerA}
                  selectedModel={modelA}
                  selectedVoices={selectedVoicesA}
                  sampleRate={sampleRateA}
                  onProviderChange={(p) => {
                    setProviderA(p)
                    setModelA('')
                    setSelectedVoicesA([])
                    setSampleRateA(null)
                  }}
                  onModelChange={setModelA}
                  onVoicesChange={setSelectedVoicesA}
                  onSampleRateChange={setSampleRateA}
                  callImportRowIds={callImportRowIdsA}
                  onCallImportRowIdsChange={setCallImportRowIdsA}
                  uploadKeys={uploadKeysA}
                  onUploadKeysChange={setUploadKeysA}
                />

                {enableComparison && (
                  <>
                    {/* VS Badge */}
                    <div className="hidden lg:flex absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10">
                      <span className="px-4 py-2 bg-gray-900 text-white rounded-full text-sm font-bold shadow-xl">VS</span>
                    </div>

                    <SourcePanel
                      label="B"
                      color="purple"
                      providers={providers}
                      sourceType={sourceTypeB}
                      onSourceTypeChange={setSourceTypeB}
                      selectedProvider={providerB}
                      selectedModel={modelB}
                      selectedVoices={selectedVoicesB}
                      sampleRate={sampleRateB}
                      onProviderChange={(p) => {
                        setProviderB(p)
                        setModelB('')
                        setSelectedVoicesB([])
                        setSampleRateB(null)
                      }}
                      onModelChange={setModelB}
                      onVoicesChange={setSelectedVoicesB}
                      onSampleRateChange={setSampleRateB}
                      callImportRowIds={callImportRowIdsB}
                      onCallImportRowIdsChange={setCallImportRowIdsB}
                      uploadKeys={uploadKeysB}
                      onUploadKeysChange={setUploadKeysB}
                    />
                  </>
                )}
              </div>

              <div className="flex justify-center">
                <Button
                  variant="primary"
                  size="lg"
                  onClick={createComparison}
                  disabled={!canRun || isCreating}
                  leftIcon={
                    isCreating ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />
                  }
                  className="px-12"
                >
                  {isCreating ? 'Starting...' : (enableComparison ? 'Run Comparison' : 'Run Benchmark')}
                </Button>
              </div>
              {isCreating && (
                <p className="text-sm text-red-600 text-center mt-3">
                  {/* Error handled by mutation */}
                </p>
              )}
            </>
          )}
        </div>
      </>
    )
  }

  // Progress step
  if (step === 'progress' && comparison) {
    const hasSecond = !!(comparison.provider_b && comparison.model_b)
    return (
      <div className="bg-white rounded-xl shadow-lg p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              {comparison.simulation_id && (
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs font-mono rounded border border-gray-200">
                  #{comparison.simulation_id}
                </span>
              )}
              {comparison.name}
            </h2>
            <div className="flex items-center gap-2 mt-1">
              <ProviderLogo provider={comparison.provider_a || ''} size="sm" />
              <span className="text-sm text-gray-500">{getProviderInfo(comparison.provider_a || '').label}</span>
              {hasSecond && (
                <>
                  <span className="text-xs text-gray-400">vs</span>
                  <ProviderLogo provider={comparison.provider_b || ''} size="sm" />
                  <span className="text-sm text-gray-500">{getProviderInfo(comparison.provider_b || '').label}</span>
                </>
              )}
              {comparison.num_runs > 1 && (
                <span className="ml-2 text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{comparison.num_runs} runs</span>
              )}
            </div>
          </div>
          <StatusBadge status={comparison.status} />
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex items-center justify-between text-sm text-gray-600 mb-2">
            <span>
              {comparison.status === 'generating' ? 'Generating audio...' : comparison.status === 'evaluating' ? 'Evaluating quality...' : comparison.status === 'completed' ? 'Complete' : 'Processing...'}
            </span>
            <span>{completedSamples}/{totalSamples} samples</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-3">
            <div
              className="bg-gradient-to-r from-blue-500 to-purple-500 h-3 rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {comparison.status === 'failed' && (
          <div className="p-4 bg-red-50 rounded-lg border border-red-200">
            <p className="text-sm text-red-700">{comparison.error_message || 'Comparison failed'}</p>
          </div>
        )}
      </div>
    )
  }

  // Results step
  if (step === 'results' && comparison) {
    return (
      <div className="space-y-6">
        <ComparisonResultsView
          comparison={comparison}
          playingId={playingId}
          onPlay={play}
          isDownloading={isDownloading}
          isCreatingReport={isCreatingReport}
          reportJob={activeReportJob || null}
          onDownloadPdf={(options) => downloadReport(comparison.id, options)}
          onGenerateAsync={(options) => createReportJob(comparison.id, options)}
          onOpenAsyncReport={() => openAsyncReport(activeReportJob)}
        />

        <div className="flex justify-center">
          <Button
            variant="primary"
            leftIcon={<RotateCcw className="w-4 h-4" />}
            onClick={resetPlayground}
          >
            Run New Comparison
          </Button>
        </div>
      </div>
    )
  }

  return null
}

const INTEGRATION_TO_PROVIDER: Record<string, string> = {
  deepgram: 'deepgram',
  elevenlabs: 'elevenlabs',
  cartesia: 'cartesia',
  sarvam: 'sarvam',
  smallest: 'smallest',
}

const PROVIDER_DISPLAY_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  deepgram: 'Deepgram',
  elevenlabs: 'ElevenLabs',
  sarvam: 'Sarvam',
  smallest: 'Smallest.ai',
}

function EvalSttPanel({
  evalSttProvider,
  setEvalSttProvider,
  evalSttModel,
  setEvalSttModel,
  voiceBundles,
}: {
  evalSttProvider: string
  setEvalSttProvider: (p: string) => void
  evalSttModel: string
  setEvalSttModel: (m: string) => void
  voiceBundles: Array<{ id: string; name: string; stt_provider?: string | null; stt_model?: string | null }>
}) {
  const [expanded, setExpanded] = useState(false)

  const { data: aiProviders = [] } = useQuery<Array<{ id: string; provider: string; is_active: boolean }>>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: integrations = [] } = useQuery<Array<{ id: string; platform: string; is_active: boolean }>>({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const activeProviderNames = useMemo(() => {
    const names = new Set<string>()
    for (const p of aiProviders) {
      if (p.is_active) names.add(p.provider.toLowerCase())
    }
    for (const i of integrations) {
      if (i.is_active) {
        const mapped = INTEGRATION_TO_PROVIDER[i.platform.toLowerCase()]
        if (mapped) names.add(mapped)
      }
    }
    return names
  }, [aiProviders, integrations])

  const activeProviderList = useMemo(
    () => Array.from(activeProviderNames).sort(),
    [activeProviderNames],
  )

  const { data: sttModelsByProvider = {} } = useQuery<Record<string, string[]>>({
    queryKey: ['voice-playground-eval-stt-models', activeProviderList],
    enabled: activeProviderList.length > 0,
    queryFn: async () => {
      const entries = await Promise.all(
        activeProviderList.map(async (provider) => {
          try {
            const options = await apiClient.getModelOptions(provider)
            return [provider, options.stt || []] as const
          } catch {
            return [provider, []] as const
          }
        }),
      )
      return Object.fromEntries(entries)
    },
  })

  const availableSttOptions = useMemo(
    () =>
      activeProviderList.flatMap((provider) =>
        (sttModelsByProvider[provider] || []).map((model) => ({
          provider,
          model,
          label: `${PROVIDER_DISPLAY_LABELS[provider] || provider} / ${model}`,
        })),
      ),
    [activeProviderList, sttModelsByProvider],
  )

  const bundleWithStt = voiceBundles.find(b => b.stt_provider && b.stt_model)
  const autoLabel = bundleWithStt
    ? `Auto — ${bundleWithStt.stt_provider} / ${bundleWithStt.stt_model} (from "${bundleWithStt.name}")`
    : 'Auto — uses first Voice Bundle with STT configured'

  const selectedValue = evalSttProvider && evalSttModel
    ? `${evalSttProvider}::${evalSttModel}`
    : ''

  const selectedLabel = selectedValue
    ? availableSttOptions.find(o => `${o.provider}::${o.model}` === selectedValue)?.label ?? `${evalSttProvider} / ${evalSttModel}`
    : 'Auto'

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-3 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-3">
          <Mic className="w-5 h-5 text-gray-500" />
          <div>
            <p className="font-medium text-gray-900 text-sm">Evaluation STT Provider</p>
            <p className="text-xs text-gray-500">
              STT service used to transcribe audio for WER/CER metrics
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">{selectedLabel}</span>
          {expanded ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-3">
          <select
            value={selectedValue}
            onChange={(e) => {
              const val = e.target.value
              if (!val) {
                setEvalSttProvider('')
                setEvalSttModel('')
              } else {
                const [p, m] = val.split('::')
                setEvalSttProvider(p)
                setEvalSttModel(m)
              }
            }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          >
            <option value="">{autoLabel}</option>
            {availableSttOptions.map((opt) => (
              <option key={`${opt.provider}::${opt.model}`} value={`${opt.provider}::${opt.model}`}>
                {opt.label}
              </option>
            ))}
          </select>
          {availableSttOptions.length === 0 && !bundleWithStt && (
            <p className="mt-2 text-xs text-amber-600">
              No STT-capable providers with STT models are configured. Add or activate an STT provider (for example OpenAI, Deepgram, ElevenLabs, Sarvam, Smallest.ai), or configure a Voice Bundle with STT to enable WER/CER evaluation.
            </p>
          )}
          {availableSttOptions.length === 0 && bundleWithStt && (
            <p className="mt-2 text-xs text-gray-500">
              No additional STT providers available. The Voice Bundle default will be used.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
