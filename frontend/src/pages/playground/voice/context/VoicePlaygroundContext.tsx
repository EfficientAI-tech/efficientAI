import { createContext, useContext, useState, useCallback, ReactNode, useMemo, useRef, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiClient } from '../../../../lib/api'
import { VoiceBundle } from '../../../../types/api'
import {
  TTSVoice,
  TTSProvider,
  TTSSample,
  TTSComparison,
  TTSComparisonSummary,
  TTSAnalyticsRow,
  CustomTTSVoice,
  TTSReportJob,
  TTSReportOptions,
  AnalyticsSortKey,
  BenchmarkMetricKey,
  DEFAULT_SAMPLE_TEXTS,
} from '../types'

type PlaygroundStep = 'configure' | 'progress' | 'blind-test' | 'results'
type ActiveTab = 'playground' | 'voices' | 'past-simulations'
type PastSubView = 'simulations' | 'analytics'

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

  // Blind test
  blindChoices: Record<number, 'A' | 'B'>
  setBlindChoices: (choices: Record<number, 'A' | 'B'>) => void
  blindPairs: Array<{ sampleIdx: number; sampleA: TTSSample; sampleB: TTSSample; flipped: boolean }>

  // Progress stats
  progressPct: number
  totalSamples: number
  completedSamples: number
  failedSamples: number

  // Mutations
  createComparison: () => void
  isCreating: boolean
  submitBlindTest: () => void
  isSubmittingBlindTest: boolean
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
  const [blindChoices, setBlindChoices] = useState<Record<number, 'A' | 'B'>>({})
  const [blindPairs, setBlindPairs] = useState<Array<{ sampleIdx: number; sampleA: TTSSample; sampleB: TTSSample; flipped: boolean }>>([])

  const { data: comparison, refetch: refetchComparison } = useQuery<TTSComparison>({
    queryKey: ['tts-comparison', activeComparisonId],
    queryFn: () => apiClient.getTTSComparison(activeComparisonId!),
    enabled: !!activeComparisonId,
    refetchInterval: activeComparisonId && step === 'progress' ? 3000 : false,
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

  // Build blind pairs
  const buildBlindPairs = useCallback((comp: TTSComparison) => {
    const pairs: typeof blindPairs = []
    const textCount = comp.sample_texts?.length || 0
    for (let i = 0; i < textCount; i++) {
      const samplesForIdx = comp.samples.filter(s => s.sample_index === i && s.status === 'completed' && s.audio_url)
      const hasSide = samplesForIdx.some(s => s.side)
      const aSamples = samplesForIdx.filter(s => hasSide ? s.side === 'A' : s.provider === comp.provider_a)
      const bSamples = samplesForIdx.filter(s => hasSide ? s.side === 'B' : s.provider === comp.provider_b)
      if (aSamples.length > 0 && bSamples.length > 0) {
        const flipped = Math.random() > 0.5
        pairs.push({
          sampleIdx: i,
          sampleA: flipped ? bSamples[0] : aSamples[0],
          sampleB: flipped ? aSamples[0] : bSamples[0],
          flipped,
        })
      }
    }
    setBlindPairs(pairs)
    setBlindChoices({})
    return pairs
  }, [])

  // Transition from progress to blind-test or results
  useEffect(() => {
    if (!comparison) return
    if (step === 'progress') {
      if (comparison.status === 'completed') {
        const pairs = buildBlindPairs(comparison)
        if (pairs.length > 0) {
          setStep('blind-test')
        } else {
          setStep('results')
        }
      }
    }
  }, [comparison, step, buildBlindPairs])

  // Progress stats
  const totalSamples = comparison?.samples?.length || 0
  const completedSamples = comparison?.samples?.filter(s => s.status === 'completed').length || 0
  const failedSamples = comparison?.samples?.filter(s => s.status === 'failed').length || 0
  const progressPct = totalSamples > 0 ? Math.round(((completedSamples + failedSamples) / totalSamples) * 100) : 0

  // Mutations
  const createMutation = useMutation({
    mutationFn: async () => {
      const payload: any = {
        provider_a: providerA,
        model_a: modelA,
        voices_a: selectedVoicesA.map(v => ({
          id: v.id, name: v.name,
          ...(sampleRateA ? { sample_rate_hz: sampleRateA } : {}),
        })),
        sample_texts: sampleTexts,
        num_runs: numRuns,
      }
      if (enableComparison) {
        payload.provider_b = providerB
        payload.model_b = modelB
        payload.voices_b = selectedVoicesB.map(v => ({
          id: v.id, name: v.name,
          ...(sampleRateB ? { sample_rate_hz: sampleRateB } : {}),
        }))
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
      setStep('progress')
      refetchPast()
    },
  })

  const blindTestMutation = useMutation({
    mutationFn: async () => {
      if (!activeComparisonId) return
      const results = blindPairs.map(pair => ({
        sample_index: pair.sampleIdx,
        preferred: blindChoices[pair.sampleIdx] || 'A',
        voice_a_id: pair.sampleA.voice_id,
        voice_b_id: pair.sampleB.voice_id,
      }))
      await apiClient.submitBlindTest(activeComparisonId, results as any)
      await refetchComparison()
    },
    onSuccess: () => {
      setStep('results')
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
  const canRun = !!(
    providerA && modelA && selectedVoicesA.length > 0 && sampleTexts.length > 0 &&
    (!enableComparison || (providerB && modelB && selectedVoicesB.length > 0))
  )

  const resetPlayground = useCallback(() => {
    stop()
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
    setBlindChoices({})
    setBlindPairs([])
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
    blindChoices,
    setBlindChoices,
    blindPairs,
    progressPct,
    totalSamples,
    completedSamples,
    failedSamples,
    createComparison: () => createMutation.mutate(),
    isCreating: createMutation.isPending,
    submitBlindTest: () => blindTestMutation.mutate(),
    isSubmittingBlindTest: blindTestMutation.isPending,
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
