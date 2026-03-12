import { Loader2, Hash, Play, RotateCcw, ArrowRight, Volume2, Plus, CheckCircle2, Pause } from 'lucide-react'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'
import SampleTextsPanel from './SampleTextsPanel'
import ProviderPanel from './ProviderPanel'
import ComparisonResultsView from './ComparisonResultsView'
import StatusBadge from './StatusBadge'

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
    canRun,
    createComparison,
    isCreating,
    comparison,
    progressPct,
    totalSamples,
    completedSamples,
    blindPairs,
    blindChoices,
    setBlindChoices,
    playingId,
    play,
    submitBlindTest,
    isSubmittingBlindTest,
    setStep,
    resetPlayground,
    activeReportJob,
    isDownloading,
    isCreatingReport,
    downloadReport,
    createReportJob,
    openAsyncReport,
  } = useVoicePlayground()

  // Configuration step
  if (step === 'configure') {
    return (
      <>
        <SampleTextsPanel />

        {/* Number of Runs */}
        <div className="bg-white rounded-xl shadow-sm p-4 border border-gray-100 flex items-center justify-between">
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
          <div className="flex items-center gap-2">
            <button
              onClick={() => setNumRuns(Math.max(1, numRuns - 1))}
              disabled={numRuns <= 1}
              className="w-8 h-8 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              −
            </button>
            <span className="w-10 text-center font-semibold text-gray-900">{numRuns}</span>
            <button
              onClick={() => setNumRuns(Math.min(10, numRuns + 1))}
              disabled={numRuns >= 10}
              className="w-8 h-8 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              +
            </button>
          </div>
        </div>

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
                <ProviderPanel
                  label="A"
                  color="blue"
                  providers={providers}
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
                />

                {enableComparison && (
                  <>
                    {/* VS Badge */}
                    <div className="hidden lg:flex absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10">
                      <span className="px-4 py-2 bg-gray-900 text-white rounded-full text-sm font-bold shadow-xl">VS</span>
                    </div>

                    <ProviderPanel
                      label="B"
                      color="purple"
                      providers={providers}
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
              <ProviderLogo provider={comparison.provider_a} size="sm" />
              <span className="text-sm text-gray-500">{getProviderInfo(comparison.provider_a).label}</span>
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

  // Blind test step
  if (step === 'blind-test' && comparison && blindPairs.length > 0) {
    return (
      <div className="space-y-6">
        <div className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl p-5 border border-amber-200">
          <div className="flex items-center gap-3 mb-2">
            <Volume2 className="w-6 h-6 text-amber-600" />
            <h2 className="text-lg font-semibold text-amber-900">Blind Listening Test</h2>
          </div>
          <p className="text-sm text-amber-800">
            Listen to Voice X and Voice Y for each sample. Choose which one sounds better.
            The provider labels are hidden so the test is unbiased.
          </p>
        </div>

        {blindPairs.map((pair, pairIdx) => (
          <div key={pairIdx} className="bg-white rounded-xl shadow-sm p-5 border border-gray-100">
            <p className="text-sm text-gray-500 mb-1 font-medium">Sample {pair.sampleIdx + 1}</p>
            <p className="text-sm text-gray-700 italic mb-4">&ldquo;{pair.sampleA.text}&rdquo;</p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Voice X */}
              <button
                onClick={() => setBlindChoices({ ...blindChoices, [pair.sampleIdx]: 'A' })}
                className={`p-4 rounded-xl border-2 transition-all ${blindChoices[pair.sampleIdx] === 'A' ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'}`}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold">X</span>
                  <span className="font-medium text-gray-900">Voice X</span>
                  {blindChoices[pair.sampleIdx] === 'A' && <CheckCircle2 className="w-5 h-5 text-blue-600 ml-auto" />}
                </div>
                {pair.sampleA.audio_url && (
                  <div
                    className="flex items-center gap-2 mt-2 p-2 bg-white rounded-lg border"
                    onClick={e => { e.stopPropagation(); play(`blind-${pairIdx}-X`, pair.sampleA.audio_url!) }}
                  >
                    {playingId === `blind-${pairIdx}-X`
                      ? <Pause className="w-4 h-4 text-blue-600" />
                      : <Play className="w-4 h-4 text-blue-600" />}
                    <span className="text-xs text-gray-600">Play sample</span>
                  </div>
                )}
              </button>

              {/* Voice Y */}
              <button
                onClick={() => setBlindChoices({ ...blindChoices, [pair.sampleIdx]: 'B' })}
                className={`p-4 rounded-xl border-2 transition-all ${blindChoices[pair.sampleIdx] === 'B' ? 'border-purple-500 bg-purple-50' : 'border-gray-200 hover:border-gray-300'}`}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center text-sm font-bold">Y</span>
                  <span className="font-medium text-gray-900">Voice Y</span>
                  {blindChoices[pair.sampleIdx] === 'B' && <CheckCircle2 className="w-5 h-5 text-purple-600 ml-auto" />}
                </div>
                {pair.sampleB.audio_url && (
                  <div
                    className="flex items-center gap-2 mt-2 p-2 bg-white rounded-lg border"
                    onClick={e => { e.stopPropagation(); play(`blind-${pairIdx}-Y`, pair.sampleB.audio_url!) }}
                  >
                    {playingId === `blind-${pairIdx}-Y`
                      ? <Pause className="w-4 h-4 text-purple-600" />
                      : <Play className="w-4 h-4 text-purple-600" />}
                    <span className="text-xs text-gray-600">Play sample</span>
                  </div>
                )}
              </button>
            </div>
          </div>
        ))}

        <div className="flex justify-center gap-4">
          <Button variant="ghost" onClick={() => setStep('results')}>
            Skip Blind Test
          </Button>
          <Button
            variant="primary"
            size="lg"
            onClick={submitBlindTest}
            disabled={Object.keys(blindChoices).length === 0 || isSubmittingBlindTest}
            leftIcon={
              isSubmittingBlindTest ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <ArrowRight className="w-5 h-5" />
              )
            }
            className="px-10"
          >
            Submit &amp; View Results
          </Button>
        </div>
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
          onDownloadPdf={() => downloadReport(comparison.id)}
          onGenerateAsync={() => createReportJob(comparison.id)}
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
