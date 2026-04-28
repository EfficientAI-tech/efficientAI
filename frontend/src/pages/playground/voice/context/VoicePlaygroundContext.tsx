import { createContext, useContext, useState, useCallback, ReactNode, useMemo, useRef, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiClient } from '../../../../lib/api'
import type {
  VoicePlaygroundSideConfig,
  VoicePlaygroundSourceType,
  VoicePlaygroundBlindTestPair,
} from '../../../../lib/api'
import { VoiceBundle } from '../../../../types/api'
import {
  TTSVoice,
  TTSProvider,
  TTSComparison,
  TTSComparisonSummary,
  TTSComparisonMode,
  TTSAnalyticsRow,
  CustomTTSVoice,
  TTSReportJob,
  TTSReportOptions,
  AnalyticsSortKey,
  BenchmarkMetricKey,
  DEFAULT_SAMPLE_TEXTS,
} from '../types'

type PlaygroundStep = 'configure' | 'progress' | 'results'
type ActiveTab = 'playground' | 'voices' | 'past-simulations' | 'blind-tests'
type PastSubView = 'simulations' | 'analytics'

export interface BenchmarkSideState {
  sourceType: VoicePlaygroundSourceType
  // TTS
  callImportRowIds: string[]
  uploadKeys: string[]
}

export interface BlindTestPairDraft {
  id: string
  text: string
  x: VoicePlaygroundBlindTestPair['x'] | null
  y: VoicePlaygroundBlindTestPair['y'] | null
}

interface VoicePlaygroundContextType {
  // Audio player
  playingId: string | null
  play: (id: string, url: string) => void
  stop: () => void

  // Active tab
  activeTab: ActiveTab
  setActiveTab: (tab: ActiveTab) => void

  // Past simulations sub-view
  pastSubView: PastSubView
  setPastSubView: (view: PastSubView) => void
  viewingPastId: string | null
  setViewingPastId: (id: string | null) => void

  // Provider data
  providers: TTSProvider[]
  providersLoading: boolean
  refetchProviders: () => void

  // Custom voices
  customVoices: CustomTTSVoice[]
  refetchCustomVoices: () => void

  // Voice bundles
  voiceBundles: VoiceBundle[]

  // Past comparisons
  pastComparisons: TTSComparisonSummary[]
  refetchPast: () => void

  // Analytics
  analyticsData: TTSAnalyticsRow[]
  analyticsLoading: boolean
  analyticsSortKey: AnalyticsSortKey
  analyticsSortAsc: boolean
  toggleAnalyticsSort: (key: AnalyticsSortKey) => void
  sortedAnalytics: TTSAnalyticsRow[]

  // Benchmark
  selectedBenchmarkMetric: BenchmarkMetricKey
  setSelectedBenchmarkMetric: (metric: BenchmarkMetricKey) => void
  benchmarkTopN: number
  setBenchmarkTopN: (n: number) => void

  // Mode chooser
  mode: TTSComparisonMode
  setMode: (m: TTSComparisonMode) => void

  // Per-side source type (benchmark mode)
  sourceTypeA: VoicePlaygroundSourceType
  setSourceTypeA: (t: VoicePlaygroundSourceType) => void
  sourceTypeB: VoicePlaygroundSourceType
  setSourceTypeB: (t: VoicePlaygroundSourceType) => void
  callImportRowIdsA: string[]
  setCallImportRowIdsA: (ids: string[]) => void
  callImportRowIdsB: string[]
  setCallImportRowIdsB: (ids: string[]) => void
  uploadKeysA: string[]
  setUploadKeysA: (keys: string[]) => void
  uploadKeysB: string[]
  setUploadKeysB: (keys: string[]) => void

  // Blind test only mode
  blindTestPairs: BlindTestPairDraft[]
  setBlindTestPairs: (pairs: BlindTestPairDraft[]) => void
  addBlindTestPair: () => void
  removeBlindTestPair: (id: string) => void
  updateBlindTestPair: (id: string, updates: Partial<BlindTestPairDraft>) => void

  // Configuration state
  providerA: string
  setProviderA: (p: string) => void
  modelA: string
  setModelA: (m: string) => void
  selectedVoicesA: TTSVoice[]
  setSelectedVoicesA: (v: TTSVoice[]) => void
  sampleRateA: number | null
  setSampleRateA: (hz: number | null) => void

  enableComparison: boolean
  setEnableComparison: (enabled: boolean) => void
  providerB: string
  setProviderB: (p: string) => void
  modelB: string
  setModelB: (m: string) => void
  selectedVoicesB: TTSVoice[]
  setSelectedVoicesB: (v: TTSVoice[]) => void
  sampleRateB: number | null
  setSampleRateB: (hz: number | null) => void

  sampleTexts: string[]
  setSampleTexts: (texts: string[]) => void
  customText: string
  setCustomText: (text: string) => void
  numRuns: number
  setNumRuns: (n: number) => void

  evalSttProvider: string
  setEvalSttProvider: (p: string) => void
  evalSttModel: string
  setEvalSttModel: (m: string) => void

  // AI sample generation
  showAiGenerate: boolean
  setShowAiGenerate: (show: boolean) => void
  aiScenario: string
  setAiScenario: (scenario: string) => void
  selectedBundleId: string
  setSelectedBundleId: (id: string) => void
  aiSampleCount: number
  setAiSampleCount: (count: number) => void
  aiSampleLength: 'short' | 'medium' | 'long' | 'paragraph'
  setAiSampleLength: (length: 'short' | 'medium' | 'long' | 'paragraph') => void
  generateSamplesMutation: ReturnType<typeof useMutation<{ samples: string[] }, Error, { voice_bundle_id?: string; provider?: string; model?: string; scenario?: string; count?: number; length?: string }>>

  // Active comparison
  step: PlaygroundStep
  setStep: (step: PlaygroundStep) => void
  activeComparisonId: string | null
  comparison: TTSComparison | undefined
  viewedComparison: TTSComparison | undefined
  viewedLoading: boolean

  // Progress stats
  progressPct: number
  totalSamples: number
  completedSamples: number
  failedSamples: number

  // Mutations
  createComparison: () => void
  isCreating: boolean
  downloadReport: (comparisonId: string, options?: TTSReportOptions) => void
  isDownloading: boolean
  createReportJob: (comparisonId: string, options?: TTSReportOptions) => void
  isCreatingReport: boolean
  deleteComparison: (id: string) => void
  isDeleting: boolean

  // Report jobs
  activeReportJob: TTSReportJob | undefined
  viewedReportJob: TTSReportJob | undefined
  openAsyncReport: (reportJob?: TTSReportJob) => void

  // Custom voice mutations
  customVoiceProvider: string
  setCustomVoiceProvider: (p: string) => void
  customVoiceId: string
  setCustomVoiceId: (id: string) => void
  customVoiceName: string
  setCustomVoiceName: (name: string) => void
  customVoiceGender: string
  setCustomVoiceGender: (gender: string) => void
  customVoiceAccent: string
  setCustomVoiceAccent: (accent: string) => void
  customVoiceDescription: string
  setCustomVoiceDescription: (desc: string) => void
  editingCustomVoiceId: string | null
  canSaveCustomVoice: boolean
  providerOptionsForVoices: string[]
  createCustomVoice: () => void
  isCreatingCustomVoice: boolean
  updateCustomVoice: () => void
  isUpdatingCustomVoice: boolean
  deleteCustomVoice: (id: string) => void
  isDeletingCustomVoice: boolean
  startEditingCustomVoice: (voice: CustomTTSVoice) => void
  resetCustomVoiceForm: () => void
  customVoiceError: string | null

  // Simulation selection
  selectedSimIds: Set<string>
  toggleSimSelection: (id: string) => void
  toggleAllSims: () => void
  allSimsSelected: boolean
  someSimsSelected: boolean
  bulkDelete: () => void
  isBulkDeleting: boolean

  // Delete confirmation
  deleteConfirm: { message: string; onConfirm: () => void } | null
  setDeleteConfirm: (confirm: { message: string; onConfirm: () => void } | null) => void

  // Helpers
  canRun: boolean
  resetPlayground: () => void
}

const VoicePlaygroundContext = createContext<VoicePlaygroundContextType | undefined>(undefined)

export function useVoicePlayground() {
  const context = useContext(VoicePlaygroundContext)
  if (!context) {
    throw new Error('useVoicePlayground must be used within VoicePlaygroundProvider')
  }
  return context
}

export function VoicePlaygroundProvider({ children }: { children: ReactNode }) {
  // Audio player
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)

  const play = useCallback((id: string, url: string) => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (playingId === id) {
      setPlayingId(null)
      return
    }
    const audio = new Audio(url)
    audio.onended = () => {
      setPlayingId(null)
      audioRef.current = null
    }
    audio.play()
    audioRef.current = audio
    setPlayingId(id)
  }, [playingId])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setPlayingId(null)
  }, [])

  // Tab state
  const [activeTab, setActiveTab] = useState<ActiveTab>('playground')
  const [pastSubView, setPastSubView] = useState<PastSubView>('simulations')
  const [viewingPastId, setViewingPastId] = useState<string | null>(null)

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null)

  // Provider data
  const { data: providers = [], isLoading: providersLoading, refetch: refetchProviders } = useQuery<TTSProvider[]>({
    queryKey: ['tts-providers'],
    queryFn: () => apiClient.listTTSProviders(),
  })

  const { data: customVoices = [], refetch: refetchCustomVoices } = useQuery<CustomTTSVoice[]>({
    queryKey: ['tts-custom-voices'],
    queryFn: () => apiClient.listCustomTTSVoices(),
    enabled: activeTab === 'voices' || activeTab === 'playground',
  })

  const { data: voiceBundles = [] } = useQuery<VoiceBundle[]>({
    queryKey: ['voice-bundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: pastComparisons = [], refetch: refetchPast } = useQuery<TTSComparisonSummary[]>({
    queryKey: ['tts-comparisons-list'],
    queryFn: () => apiClient.listTTSComparisons(),
  })

  // Analytics
  const [analyticsSortKey, setAnalyticsSortKey] = useState<AnalyticsSortKey>('avg_mos')
  const [analyticsSortAsc, setAnalyticsSortAsc] = useState(false)
  const [selectedBenchmarkMetric, setSelectedBenchmarkMetric] = useState<BenchmarkMetricKey>('avg_mos')
  const [benchmarkTopN, setBenchmarkTopN] = useState(10)

  const { data: analyticsData = [], isLoading: analyticsLoading } = useQuery<TTSAnalyticsRow[]>({
    queryKey: ['tts-analytics'],
    queryFn: () => apiClient.getTTSAnalytics(),
    enabled: activeTab === 'past-simulations' && pastSubView === 'analytics',
  })

  const sortedAnalytics = useMemo(() => {
    return [...analyticsData].sort((a, b) => {
      const aVal = a[analyticsSortKey]
      const bVal = b[analyticsSortKey]
      if (aVal == null && bVal == null) return 0
      if (aVal == null) return analyticsSortAsc ? -1 : 1
      if (bVal == null) return analyticsSortAsc ? 1 : -1
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return analyticsSortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
      }
      return analyticsSortAsc ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number)
    })
  }, [analyticsData, analyticsSortKey, analyticsSortAsc])

  const toggleAnalyticsSort = useCallback((key: AnalyticsSortKey) => {
    if (analyticsSortKey === key) {
      setAnalyticsSortAsc(!analyticsSortAsc)
    } else {
      setAnalyticsSortKey(key)
      setAnalyticsSortAsc(key === 'provider' || key === 'model' || key === 'voice_name')
    }
  }, [analyticsSortKey, analyticsSortAsc])

  // Mode + per-side source state
  const [mode, setMode] = useState<TTSComparisonMode>('benchmark')
  const [sourceTypeA, setSourceTypeA] = useState<VoicePlaygroundSourceType>('tts')
  const [sourceTypeB, setSourceTypeB] = useState<VoicePlaygroundSourceType>('tts')
  const [callImportRowIdsA, setCallImportRowIdsA] = useState<string[]>([])
  const [callImportRowIdsB, setCallImportRowIdsB] = useState<string[]>([])
  const [uploadKeysA, setUploadKeysA] = useState<string[]>([])
  const [uploadKeysB, setUploadKeysB] = useState<string[]>([])

  // Blind-test-only pair drafts
  const [blindTestPairs, setBlindTestPairs] = useState<BlindTestPairDraft[]>([
    { id: 'pair-1', text: '', x: null, y: null },
  ])

  const addBlindTestPair = useCallback(() => {
    setBlindTestPairs((prev) => [
      ...prev,
      { id: `pair-${Date.now()}-${prev.length + 1}`, text: '', x: null, y: null },
    ])
  }, [])

  const removeBlindTestPair = useCallback((id: string) => {
    setBlindTestPairs((prev) => prev.filter((p) => p.id !== id))
  }, [])

  const updateBlindTestPair = useCallback((id: string, updates: Partial<BlindTestPairDraft>) => {
    setBlindTestPairs((prev) => prev.map((p) => (p.id === id ? { ...p, ...updates } : p)))
  }, [])

  // Configuration state
  const [providerA, setProviderA] = useState('')
  const [modelA, setModelA] = useState('')
  const [selectedVoicesA, setSelectedVoicesA] = useState<TTSVoice[]>([])
  const [sampleRateA, setSampleRateA] = useState<number | null>(null)

  const [enableComparison, setEnableComparison] = useState(false)
  const [providerB, setProviderB] = useState('')
  const [modelB, setModelB] = useState('')
  const [selectedVoicesB, setSelectedVoicesB] = useState<TTSVoice[]>([])
  const [sampleRateB, setSampleRateB] = useState<number | null>(null)

  const [sampleTexts, setSampleTexts] = useState<string[]>(DEFAULT_SAMPLE_TEXTS.slice(0, 1))
  const [customText, setCustomText] = useState('')
  const [numRuns, setNumRuns] = useState(1)

  const [evalSttProvider, setEvalSttProvider] = useState('')
  const [evalSttModel, setEvalSttModel] = useState('')

  // AI sample generation
  const [showAiGenerate, setShowAiGenerate] = useState(false)
  const [aiScenario, setAiScenario] = useState('')
  const [selectedBundleId, setSelectedBundleId] = useState('')
  const [aiSampleCount, setAiSampleCount] = useState(5)
  const [aiSampleLength, setAiSampleLength] = useState<'short' | 'medium' | 'long' | 'paragraph'>('short')

  const generateSamplesMutation = useMutation({
    mutationFn: (params: { voice_bundle_id?: string; provider?: string; model?: string; scenario?: string; count?: number; length?: string }) =>
      apiClient.generateSampleTexts(params),
    onSuccess: (data) => {
      setSampleTexts(prev => [...prev, ...data.samples])
      setShowAiGenerate(false)
      setAiScenario('')
    },
  })

  // Custom voice state
  const [customVoiceProvider, setCustomVoiceProvider] = useState('')
  const [customVoiceId, setCustomVoiceId] = useState('')
  const [customVoiceName, setCustomVoiceName] = useState('')
  const [customVoiceGender, setCustomVoiceGender] = useState('')
  const [customVoiceAccent, setCustomVoiceAccent] = useState('')
  const [customVoiceDescription, setCustomVoiceDescription] = useState('')
  const [editingCustomVoiceId, setEditingCustomVoiceId] = useState<string | null>(null)

  const canSaveCustomVoice = !!(customVoiceProvider && customVoiceId.trim() && customVoiceName.trim())
  const providerOptionsForVoices = providers.map(p => p.provider)

  // Active comparison
  const [activeComparisonId, setActiveComparisonId] = useState<string | null>(null)
  const [step, setStep] = useState<PlaygroundStep>('configure')

  const { data: comparison } = useQuery<TTSComparison>({
    queryKey: ['tts-comparison', activeComparisonId],
    queryFn: () => apiClient.getTTSComparison(activeComparisonId!),
    enabled: !!activeComparisonId,
    refetchInterval: (query) => {
      const c = query.state.data
      if (!activeComparisonId) return false
      if (step === 'progress') return 3000
      // Keep polling while evaluation is still finishing in the background.
      if (step === 'results' && c?.status === 'evaluating') return 5000
      return false
    },
  })

  const { data: viewedComparison, isLoading: viewedLoading } = useQuery<TTSComparison>({
    queryKey: ['tts-comparison', viewingPastId],
    queryFn: () => apiClient.getTTSComparison(viewingPastId!),
    enabled: !!viewingPastId,
  })

  // Report jobs
  const [reportJobByComparisonId, setReportJobByComparisonId] = useState<Record<string, string>>({})
  const activeReportJobId = comparison ? reportJobByComparisonId[comparison.id] : undefined
  const viewedReportJobId = viewedComparison ? reportJobByComparisonId[viewedComparison.id] : undefined

  const { data: activeReportJob } = useQuery<TTSReportJob>({
    queryKey: ['tts-report-job', activeReportJobId],
    queryFn: () => apiClient.getTTSComparisonReportJob(activeReportJobId!),
    enabled: !!activeReportJobId,
    refetchInterval: 4000,
  })

  const { data: viewedReportJob } = useQuery<TTSReportJob>({
    queryKey: ['tts-report-job', viewedReportJobId],
    queryFn: () => apiClient.getTTSComparisonReportJob(viewedReportJobId!),
    enabled: !!viewedReportJobId,
    refetchInterval: 4000,
  })

  // Transition from progress -> results as soon as audio is ready.
  // Evaluation may still be running in the background; the results view
  // surfaces a "create blind test" affordance immediately so the user can
  // start collecting external responses without waiting for metrics.
  useEffect(() => {
    if (!comparison) return
    if (step !== 'progress') return
    const audioReady =
      comparison.status === 'evaluating' || comparison.status === 'completed'
    if (audioReady) {
      setStep('results')
    }
  }, [comparison, step])

  // Progress stats
  const totalSamples = comparison?.samples?.length || 0
  const completedSamples = comparison?.samples?.filter(s => s.status === 'completed').length || 0
  const failedSamples = comparison?.samples?.filter(s => s.status === 'failed').length || 0
  const progressPct = totalSamples > 0 ? Math.round(((completedSamples + failedSamples) / totalSamples) * 100) : 0

  // Mutations
  const buildSidePayload = useCallback(
    (
      sourceType: VoicePlaygroundSourceType,
      provider: string,
      model: string,
      voices: TTSVoice[],
      sampleRate: number | null,
      callImportRowIds: string[],
      uploadKeys: string[],
    ): VoicePlaygroundSideConfig => {
      if (sourceType === 'tts') {
        return {
          source_type: 'tts',
          provider,
          model,
          voices: voices.map((v) => ({
            id: v.id,
            name: v.name,
            ...(sampleRate ? { sample_rate_hz: sampleRate } : {}),
          })),
        }
      }
      if (sourceType === 'recording') {
        return { source_type: 'recording', call_import_row_ids: callImportRowIds }
      }
      return { source_type: 'upload', upload_s3_keys: uploadKeys }
    },
    [],
  )

  const createMutation = useMutation({
    mutationFn: async () => {
      if (mode === 'blind_test_only') {
        const pairs: VoicePlaygroundBlindTestPair[] = blindTestPairs
          .filter((p) => p.x && p.y)
          .map((p) => ({
            text: p.text || undefined,
            x: p.x as VoicePlaygroundBlindTestPair['x'],
            y: p.y as VoicePlaygroundBlindTestPair['y'],
          }))
        if (pairs.length === 0) {
          throw new Error('Add at least one blind-test pair with X and Y audio selected')
        }
        const payload: any = { mode: 'blind_test_only', pairs }
        if (evalSttProvider && evalSttModel) {
          payload.eval_stt_provider = evalSttProvider
          payload.eval_stt_model = evalSttModel
        }
        const comp = await apiClient.createTTSComparison(payload)
        await apiClient.generateTTSComparison(comp.id)
        return comp
      }

      const payload: any = {
        mode: 'benchmark',
        sample_texts: sampleTexts,
        num_runs: numRuns,
        side_a: buildSidePayload(
          sourceTypeA,
          providerA,
          modelA,
          selectedVoicesA,
          sampleRateA,
          callImportRowIdsA,
          uploadKeysA,
        ),
      }
      if (enableComparison) {
        payload.side_b = buildSidePayload(
          sourceTypeB,
          providerB,
          modelB,
          selectedVoicesB,
          sampleRateB,
          callImportRowIdsB,
          uploadKeysB,
        )
      }
      if (evalSttProvider && evalSttModel) {
        payload.eval_stt_provider = evalSttProvider
        payload.eval_stt_model = evalSttModel
      }
      const comp = await apiClient.createTTSComparison(payload)
      await apiClient.generateTTSComparison(comp.id)
      return comp
    },
    onSuccess: (comp) => {
      setActiveComparisonId(comp.id)
      setStep(mode === 'blind_test_only' ? 'results' : 'progress')
      refetchPast()
    },
  })

  const downloadReportMutation = useMutation({
    mutationFn: ({ comparisonId, options }: { comparisonId: string; options?: TTSReportOptions }) =>
      apiClient.downloadTTSComparisonReport(comparisonId, false, options),
    onSuccess: (blob, variables) => {
      const filename = `voice-playground-report-${variables.comparisonId.slice(0, 8)}.pdf`
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    },
  })

  const createReportJobMutation = useMutation({
    mutationFn: ({ comparisonId, options }: { comparisonId: string; options?: TTSReportOptions }) =>
      apiClient.createTTSComparisonReportJob(comparisonId, options),
    onSuccess: (job) => {
      setReportJobByComparisonId(prev => ({ ...prev, [job.comparison_id]: job.id }))
    },
  })

  const openAsyncReport = useCallback((reportJob?: TTSReportJob) => {
    if (!reportJob?.download_url) return
    window.open(reportJob.download_url, '_blank', 'noopener,noreferrer')
  }, [])

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteTTSComparison(id),
    onSuccess: (_data, id) => {
      setSelectedSimIds(prev => { const next = new Set(prev); next.delete(id); return next })
      refetchPast()
    },
  })

  // Custom voice mutations
  const createCustomVoiceMutation = useMutation({
    mutationFn: () => apiClient.createCustomTTSVoice({
      provider: customVoiceProvider,
      voice_id: customVoiceId,
      name: customVoiceName,
      gender: customVoiceGender || undefined,
      accent: customVoiceAccent || undefined,
      description: customVoiceDescription || undefined,
    }),
    onSuccess: async () => {
      resetCustomVoiceForm()
      await Promise.all([refetchCustomVoices(), refetchProviders()])
    },
  })

  const updateCustomVoiceMutation = useMutation({
    mutationFn: () => apiClient.updateCustomTTSVoice(editingCustomVoiceId!, {
      voice_id: customVoiceId,
      name: customVoiceName,
      gender: customVoiceGender,
      accent: customVoiceAccent,
      description: customVoiceDescription,
    }),
    onSuccess: async () => {
      resetCustomVoiceForm()
      await Promise.all([refetchCustomVoices(), refetchProviders()])
    },
  })

  const deleteCustomVoiceMutation = useMutation({
    mutationFn: (voiceId: string) => apiClient.deleteCustomTTSVoice(voiceId),
    onSuccess: async () => {
      await Promise.all([refetchCustomVoices(), refetchProviders()])
    },
  })

  const startEditingCustomVoice = useCallback((voice: CustomTTSVoice) => {
    setEditingCustomVoiceId(voice.id)
    setCustomVoiceProvider(voice.provider)
    setCustomVoiceId(voice.voice_id)
    setCustomVoiceName(voice.name)
    setCustomVoiceGender(voice.gender === 'Unknown' ? '' : voice.gender)
    setCustomVoiceAccent(voice.accent === 'Unknown' ? '' : voice.accent)
    setCustomVoiceDescription(voice.description || '')
  }, [])

  const resetCustomVoiceForm = useCallback(() => {
    setEditingCustomVoiceId(null)
    setCustomVoiceProvider('')
    setCustomVoiceId('')
    setCustomVoiceName('')
    setCustomVoiceGender('')
    setCustomVoiceAccent('')
    setCustomVoiceDescription('')
  }, [])

  // Simulation selection
  const [selectedSimIds, setSelectedSimIds] = useState<Set<string>>(new Set())
  const allSimsSelected = pastComparisons.length > 0 && selectedSimIds.size === pastComparisons.length
  const someSimsSelected = selectedSimIds.size > 0

  const toggleSimSelection = useCallback((id: string) => {
    setSelectedSimIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleAllSims = useCallback(() => {
    if (allSimsSelected) {
      setSelectedSimIds(new Set())
    } else {
      setSelectedSimIds(new Set(pastComparisons.map(pc => pc.id)))
    }
  }, [allSimsSelected, pastComparisons])

  const bulkDeleteMutation = useMutation({
    mutationFn: async () => {
      for (const id of selectedSimIds) {
        await apiClient.deleteTTSComparison(id)
      }
    },
    onSuccess: () => {
      setSelectedSimIds(new Set())
      refetchPast()
    },
  })

  // Helpers
  const sideAReady = useMemo(() => {
    if (sourceTypeA === 'tts') {
      return !!(providerA && modelA && selectedVoicesA.length > 0)
    }
    if (sourceTypeA === 'recording') {
      return callImportRowIdsA.length >= sampleTexts.length && sampleTexts.length > 0
    }
    return uploadKeysA.length >= sampleTexts.length && sampleTexts.length > 0
  }, [sourceTypeA, providerA, modelA, selectedVoicesA, callImportRowIdsA, uploadKeysA, sampleTexts.length])

  const sideBReady = useMemo(() => {
    if (!enableComparison) return true
    if (sourceTypeB === 'tts') {
      return !!(providerB && modelB && selectedVoicesB.length > 0)
    }
    if (sourceTypeB === 'recording') {
      return callImportRowIdsB.length >= sampleTexts.length && sampleTexts.length > 0
    }
    return uploadKeysB.length >= sampleTexts.length && sampleTexts.length > 0
  }, [enableComparison, sourceTypeB, providerB, modelB, selectedVoicesB, callImportRowIdsB, uploadKeysB, sampleTexts.length])

  const blindTestPairsReady = useMemo(() => {
    if (mode !== 'blind_test_only') return true
    return blindTestPairs.length > 0 && blindTestPairs.every((p) => !!p.x && !!p.y)
  }, [mode, blindTestPairs])

  const canRun =
    mode === 'blind_test_only'
      ? blindTestPairsReady
      : sampleTexts.length > 0 && sideAReady && sideBReady

  const resetPlayground = useCallback(() => {
    stop()
    setMode('benchmark')
    setSourceTypeA('tts')
    setSourceTypeB('tts')
    setCallImportRowIdsA([])
    setCallImportRowIdsB([])
    setUploadKeysA([])
    setUploadKeysB([])
    setBlindTestPairs([{ id: 'pair-1', text: '', x: null, y: null }])
    setProviderA('')
    setProviderB('')
    setModelA('')
    setModelB('')
    setEnableComparison(false)
    setSelectedVoicesA([])
    setSelectedVoicesB([])
    setSampleTexts(DEFAULT_SAMPLE_TEXTS.slice(0, 1))
    setNumRuns(1)
    setEvalSttProvider('')
    setEvalSttModel('')
    setActiveComparisonId(null)
    setStep('configure')
  }, [stop])

  const customVoiceError = useMemo(() => {
    if (createCustomVoiceMutation.isError) {
      return (createCustomVoiceMutation.error as any)?.response?.data?.detail || 'Failed to create custom voice'
    }
    if (updateCustomVoiceMutation.isError) {
      return (updateCustomVoiceMutation.error as any)?.response?.data?.detail || 'Failed to update custom voice'
    }
    return null
  }, [createCustomVoiceMutation.isError, createCustomVoiceMutation.error, updateCustomVoiceMutation.isError, updateCustomVoiceMutation.error])

  const value: VoicePlaygroundContextType = {
    playingId,
    play,
    stop,
    activeTab,
    setActiveTab,
    pastSubView,
    setPastSubView,
    viewingPastId,
    setViewingPastId,
    providers,
    providersLoading,
    refetchProviders,
    customVoices,
    refetchCustomVoices,
    voiceBundles,
    pastComparisons,
    refetchPast,
    analyticsData,
    analyticsLoading,
    analyticsSortKey,
    analyticsSortAsc,
    toggleAnalyticsSort,
    sortedAnalytics,
    selectedBenchmarkMetric,
    setSelectedBenchmarkMetric,
    benchmarkTopN,
    setBenchmarkTopN,
    mode,
    setMode,
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
    blindTestPairs,
    setBlindTestPairs,
    addBlindTestPair,
    removeBlindTestPair,
    updateBlindTestPair,
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
    sampleTexts,
    setSampleTexts,
    customText,
    setCustomText,
    numRuns,
    setNumRuns,
    evalSttProvider,
    setEvalSttProvider,
    evalSttModel,
    setEvalSttModel,
    showAiGenerate,
    setShowAiGenerate,
    aiScenario,
    setAiScenario,
    selectedBundleId,
    setSelectedBundleId,
    aiSampleCount,
    setAiSampleCount,
    aiSampleLength,
    setAiSampleLength,
    generateSamplesMutation,
    step,
    setStep,
    activeComparisonId,
    comparison,
    viewedComparison,
    viewedLoading,
    progressPct,
    totalSamples,
    completedSamples,
    failedSamples,
    createComparison: () => createMutation.mutate(),
    isCreating: createMutation.isPending,
    downloadReport: (id: string, options?: TTSReportOptions) =>
      downloadReportMutation.mutate({ comparisonId: id, options }),
    isDownloading: downloadReportMutation.isPending,
    createReportJob: (id: string, options?: TTSReportOptions) =>
      createReportJobMutation.mutate({ comparisonId: id, options }),
    isCreatingReport: createReportJobMutation.isPending,
    deleteComparison: (id: string) => deleteMutation.mutate(id),
    isDeleting: deleteMutation.isPending,
    activeReportJob,
    viewedReportJob,
    openAsyncReport,
    customVoiceProvider,
    setCustomVoiceProvider,
    customVoiceId,
    setCustomVoiceId,
    customVoiceName,
    setCustomVoiceName,
    customVoiceGender,
    setCustomVoiceGender,
    customVoiceAccent,
    setCustomVoiceAccent,
    customVoiceDescription,
    setCustomVoiceDescription,
    editingCustomVoiceId,
    canSaveCustomVoice,
    providerOptionsForVoices,
    createCustomVoice: () => createCustomVoiceMutation.mutate(),
    isCreatingCustomVoice: createCustomVoiceMutation.isPending,
    updateCustomVoice: () => updateCustomVoiceMutation.mutate(),
    isUpdatingCustomVoice: updateCustomVoiceMutation.isPending,
    deleteCustomVoice: (id: string) => deleteCustomVoiceMutation.mutate(id),
    isDeletingCustomVoice: deleteCustomVoiceMutation.isPending,
    startEditingCustomVoice,
    resetCustomVoiceForm,
    customVoiceError,
    selectedSimIds,
    toggleSimSelection,
    toggleAllSims,
    allSimsSelected,
    someSimsSelected,
    bulkDelete: () => bulkDeleteMutation.mutate(),
    isBulkDeleting: bulkDeleteMutation.isPending,
    deleteConfirm,
    setDeleteConfirm,
    canRun,
    resetPlayground,
  }

  return (
    <VoicePlaygroundContext.Provider value={value}>
      {children}
    </VoicePlaygroundContext.Provider>
  )
}
