import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { MODEL_PROVIDER_CONFIG } from '../config/providers'
import { ModelProvider, VoiceBundle } from '../types/api'
import Button from '../components/Button'
import {
    BarChart,
    Bar,
    Cell,
    LabelList,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
} from 'recharts'
import {
    Play,
    Pause,
    Volume2,
    Trophy,
    Mic,
    RotateCcw,
    X,
    Loader2,
    FileText,
    CheckCircle2,
    XCircle,
    Clock,
    ChevronDown,
    ChevronUp,
    ArrowRight,
    ArrowLeft,
    Headphones,
    Hash,
    History,
    Trash2,
    Sparkles,
    Bot,
    Pencil,
    Check,
    BarChart3,
    ArrowUpDown,
    Plus,
    Save,
} from 'lucide-react'

// ============ TYPES ============

interface TTSVoice {
    id: string
    name: string
    gender: string
    accent: string
    is_custom?: boolean
    custom_voice_id?: string
    description?: string
}

interface TTSProvider {
    provider: string
    models: string[]
    voices: TTSVoice[]
    supported_sample_rates?: number[]
}

interface TTSSample {
    id: string
    provider: string
    model: string
    voice_id: string
    voice_name: string
    side?: string | null
    sample_index: number
    run_index: number
    text: string
    audio_url: string | null
    audio_s3_key: string | null
    duration_seconds: number | null
    latency_ms: number | null
    ttfb_ms: number | null
    evaluation_metrics: Record<string, number | string | null> | null
    status: string
    error_message: string | null
}

interface TTSComparison {
    id: string
    simulation_id: string | null
    name: string
    status: string
    provider_a: string
    model_a: string
    voices_a: Array<{ id: string; name: string; sample_rate_hz?: number }>
    provider_b?: string | null
    model_b?: string | null
    voices_b?: Array<{ id: string; name: string; sample_rate_hz?: number }>
    sample_texts: string[]
    num_runs: number
    blind_test_results: Array<{ sample_index: number; preferred: string }> | null
    evaluation_summary: Record<string, any> | null
    error_message: string | null
    samples: TTSSample[]
    created_at: string
    updated_at: string
}

interface TTSComparisonSummary {
    id: string
    simulation_id: string | null
    name: string
    status: string
    provider_a: string
    model_a: string
    provider_b?: string | null
    model_b?: string | null
    sample_count: number
    num_runs: number
    created_at: string
}

interface TTSAnalyticsRow {
    provider: string
    model: string
    voice_id: string
    voice_name: string
    sample_count: number
    avg_mos: number | null
    avg_valence: number | null
    avg_arousal: number | null
    avg_prosody: number | null
    avg_latency_ms: number | null
    avg_ttfb_ms: number | null
}

interface CustomTTSVoice {
    id: string
    provider: string
    voice_id: string
    name: string
    gender: string
    accent: string
    description?: string | null
    is_custom: boolean
    created_at?: string | null
    updated_at?: string | null
}

type AnalyticsSortKey = 'provider' | 'model' | 'voice_name' | 'sample_count' | 'avg_mos' | 'avg_valence' | 'avg_arousal' | 'avg_prosody' | 'avg_latency_ms' | 'avg_ttfb_ms'
type BenchmarkMetricKey = 'avg_mos' | 'avg_valence' | 'avg_arousal' | 'avg_prosody' | 'avg_latency_ms' | 'avg_ttfb_ms'

const BENCHMARK_METRIC_OPTIONS: Array<{
    key: BenchmarkMetricKey
    title: string
    subtitle: string
    higherIsBetter: boolean
    maxValue?: number
    unit?: string
}> = [
    { key: 'avg_mos', title: 'INTELLIGENCE', subtitle: 'Average MOS Score; Higher is better', higherIsBetter: true, maxValue: 5 },
    { key: 'avg_valence', title: 'VALENCE', subtitle: 'Average Emotional Valence; Higher is better', higherIsBetter: true, maxValue: 1 },
    { key: 'avg_arousal', title: 'AROUSAL', subtitle: 'Average Emotional Arousal; Higher is better', higherIsBetter: true, maxValue: 1 },
    { key: 'avg_prosody', title: 'PROSODY', subtitle: 'Average Prosody Score; Higher is better', higherIsBetter: true, maxValue: 5 },
    { key: 'avg_ttfb_ms', title: 'TTFB', subtitle: 'Time-To-First-Byte (ms); Lower is better', higherIsBetter: false, unit: 'ms' },
    { key: 'avg_latency_ms', title: 'TOTAL LATENCY', subtitle: 'Total Synthesis Latency (ms); Lower is better', higherIsBetter: false, unit: 'ms' },
]

// ============ CONSTANTS ============

const DEFAULT_SAMPLE_TEXTS = [
    "Hello! Thank you for calling customer support. How may I assist you today?",
    "Your order number is 1-2-3-4-5-6-7-8-9. It will be delivered on January 15th, 2025.",
    "I understand your concern. Let me look into this for you right away.",
    "The total amount due is $1,234.56. Would you like to proceed with the payment?",
    "Is there anything else I can help you with today? We appreciate your business!",
]

function getProviderInfo(key: string): { label: string; logo: string | null } {
    const enumKey = key.toUpperCase() as keyof typeof ModelProvider
    const enumVal = ModelProvider[enumKey]
    if (enumVal && MODEL_PROVIDER_CONFIG[enumVal]) {
        return { label: MODEL_PROVIDER_CONFIG[enumVal].label, logo: MODEL_PROVIDER_CONFIG[enumVal].logo }
    }
    return { label: key.charAt(0).toUpperCase() + key.slice(1), logo: null }
}

function ProviderLogo({ provider, size = 'md' }: { provider: string; size?: 'sm' | 'md' | 'lg' }) {
    const { logo, label } = getProviderInfo(provider)
    const dims = size === 'sm' ? 'w-5 h-5' : size === 'lg' ? 'w-10 h-10' : 'w-7 h-7'
    const containerDims = size === 'sm' ? 'w-6 h-6' : size === 'lg' ? 'w-12 h-12' : 'w-8 h-8'
    if (!logo) {
        return (
            <div className={`${containerDims} bg-gray-100 rounded-lg flex items-center justify-center border border-gray-200`}>
                <Volume2 className={`${size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} text-gray-400`} />
            </div>
        )
    }
    return (
        <div className={`${containerDims} bg-white rounded-lg flex items-center justify-center border border-gray-200 p-0.5`}>
            <img src={logo} alt={label} className={`${dims} object-contain`} />
        </div>
    )
}


// ============ AUDIO PLAYER HOOK ============

function useAudioPlayer() {
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
        audio.onended = () => setPlayingId(null)
        audio.onerror = () => setPlayingId(null)
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

    return { playingId, play, stop }
}

// ============ SUB-COMPONENTS ============

function StatusBadge({ status }: { status: string }) {
    const styles: Record<string, string> = {
        pending: 'bg-gray-100 text-gray-700',
        generating: 'bg-yellow-100 text-yellow-800',
        evaluating: 'bg-blue-100 text-blue-800',
        completed: 'bg-green-100 text-green-800',
        failed: 'bg-red-100 text-red-700',
    }
    const icons: Record<string, React.ReactNode> = {
        pending: <Clock className="w-3 h-3" />,
        generating: <Loader2 className="w-3 h-3 animate-spin" />,
        evaluating: <Loader2 className="w-3 h-3 animate-spin" />,
        completed: <CheckCircle2 className="w-3 h-3" />,
        failed: <XCircle className="w-3 h-3" />,
    }
    return (
        <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${styles[status] || styles.pending}`}>
            {icons[status] || icons.pending}
            {status}
        </span>
    )
}

function MetricCard({ label, valueA, valueB, unit, higherIsBetter = true }: {
    label: string; valueA: number | null | undefined; valueB: number | null | undefined; unit?: string; higherIsBetter?: boolean
}) {
    const aVal = valueA ?? null
    const bVal = valueB ?? null
    const isSingleProvider = bVal === null
    const aWins = aVal !== null && bVal !== null && (higherIsBetter ? aVal > bVal : aVal < bVal)
    const bWins = aVal !== null && bVal !== null && (higherIsBetter ? bVal > aVal : bVal < aVal)

    return (
        <div className="bg-white rounded-lg p-4 border border-gray-100 shadow-sm">
            <p className="text-xs text-gray-500 mb-2 font-medium">{label}</p>
            <div className="flex items-baseline gap-3">
                <span className={`text-lg font-bold ${aWins ? 'text-blue-600' : 'text-gray-700'}`}>
                    {aVal !== null ? `${aVal}${unit || ''}` : '—'}
                </span>
                {!isSingleProvider && (
                    <>
                        <span className="text-xs text-gray-400">vs</span>
                        <span className={`text-lg font-bold ${bWins ? 'text-purple-600' : 'text-gray-700'}`}>
                            {bVal !== null ? `${bVal}${unit || ''}` : '—'}
                        </span>
                    </>
                )}
            </div>
        </div>
    )
}

// ============ MAIN COMPONENT ============

export default function VoicePlayground() {
    const { playingId, play, stop } = useAudioPlayer()
    const [activeTab, setActiveTab] = useState<'playground' | 'voices' | 'past-simulations'>('playground')
    const [viewingPastId, setViewingPastId] = useState<string | null>(null)
    const [pastSubView, setPastSubView] = useState<'simulations' | 'analytics'>('simulations')
    const [analyticsSortKey, setAnalyticsSortKey] = useState<AnalyticsSortKey>('avg_mos')
    const [analyticsSortAsc, setAnalyticsSortAsc] = useState(false)
    const [selectedBenchmarkMetric, setSelectedBenchmarkMetric] = useState<BenchmarkMetricKey>('avg_mos')
    const [benchmarkTopN, setBenchmarkTopN] = useState(10)

    // --- Delete confirmation modal ---
    const [deleteConfirm, setDeleteConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null)

    // --- Provider data ---
    const { data: providers = [], isLoading: providersLoading, refetch: refetchProviders } = useQuery<TTSProvider[]>({
        queryKey: ['tts-providers'],
        queryFn: () => apiClient.listTTSProviders(),
    })

    const { data: customVoices = [], refetch: refetchCustomVoices } = useQuery<CustomTTSVoice[]>({
        queryKey: ['tts-custom-voices'],
        queryFn: () => apiClient.listCustomTTSVoices(),
        enabled: activeTab === 'voices' || activeTab === 'playground',
    })

    // --- Voice bundles (for AI sample generation) ---
    const { data: voiceBundles = [] } = useQuery<VoiceBundle[]>({
        queryKey: ['voice-bundles'],
        queryFn: () => apiClient.listVoiceBundles(),
    })

    // --- Past comparisons ---
    const { data: pastComparisons = [], refetch: refetchPast } = useQuery<TTSComparisonSummary[]>({
        queryKey: ['tts-comparisons-list'],
        queryFn: () => apiClient.listTTSComparisons(),
    })

    // --- Analytics ---
    const { data: analyticsData = [], isLoading: analyticsLoading } = useQuery<TTSAnalyticsRow[]>({
        queryKey: ['tts-analytics'],
        queryFn: () => apiClient.getTTSAnalytics(),
        enabled: activeTab === 'past-simulations' && pastSubView === 'analytics',
    })

    const sortedAnalytics = [...analyticsData].sort((a, b) => {
        const aVal = a[analyticsSortKey]
        const bVal = b[analyticsSortKey]
        if (aVal == null && bVal == null) return 0
        if (aVal == null) return 1
        if (bVal == null) return -1
        if (typeof aVal === 'string' && typeof bVal === 'string') {
            return analyticsSortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
        }
        return analyticsSortAsc ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number)
    })

    const analyticsOverview = useMemo(() => {
        if (analyticsData.length === 0) {
            return {
                totalVoices: 0,
                totalSamples: 0,
                avgMos: null as number | null,
                avgTtfb: null as number | null,
                avgLatency: null as number | null,
            }
        }
        const totalSamples = analyticsData.reduce((sum, row) => sum + (row.sample_count || 0), 0)
        const weightedMos = analyticsData.reduce((sum, row) => sum + ((row.avg_mos || 0) * (row.sample_count || 0)), 0)
        const weightedTtfb = analyticsData.reduce((sum, row) => sum + ((row.avg_ttfb_ms || 0) * (row.sample_count || 0)), 0)
        const weightedLatency = analyticsData.reduce((sum, row) => sum + ((row.avg_latency_ms || 0) * (row.sample_count || 0)), 0)
        const mosWeight = analyticsData.reduce((sum, row) => sum + (row.avg_mos != null ? (row.sample_count || 0) : 0), 0)
        const ttfbWeight = analyticsData.reduce((sum, row) => sum + (row.avg_ttfb_ms != null ? (row.sample_count || 0) : 0), 0)
        const latencyWeight = analyticsData.reduce((sum, row) => sum + (row.avg_latency_ms != null ? (row.sample_count || 0) : 0), 0)
        return {
            totalVoices: analyticsData.length,
            totalSamples,
            avgMos: mosWeight > 0 ? Number((weightedMos / mosWeight).toFixed(2)) : null,
            avgTtfb: ttfbWeight > 0 ? Number((weightedTtfb / ttfbWeight).toFixed(0)) : null,
            avgLatency: latencyWeight > 0 ? Number((weightedLatency / latencyWeight).toFixed(0)) : null,
        }
    }, [analyticsData])

    const benchmarkRows = useMemo(() => {
        return analyticsData.map((row) => ({
            id: `${row.provider}-${row.model}-${row.voice_id}`,
            provider: row.provider,
            model: row.model,
            voice_name: row.voice_name,
            sample_count: row.sample_count,
            avg_mos: row.avg_mos,
            avg_valence: row.avg_valence,
            avg_arousal: row.avg_arousal,
            avg_prosody: row.avg_prosody,
            avg_ttfb_ms: row.avg_ttfb_ms,
            avg_latency_ms: row.avg_latency_ms,
            label: `${row.voice_name} • ${getProviderInfo(row.provider).label} • ${row.model}`,
            short_label: row.voice_name.length > 16 ? `${row.voice_name.slice(0, 16)}...` : row.voice_name,
        }))
    }, [analyticsData])

    const selectedBenchmarkConfig = useMemo(
        () => BENCHMARK_METRIC_OPTIONS.find(opt => opt.key === selectedBenchmarkMetric) || BENCHMARK_METRIC_OPTIONS[0],
        [selectedBenchmarkMetric]
    )

    function toggleAnalyticsSort(key: AnalyticsSortKey) {
        if (analyticsSortKey === key) {
            setAnalyticsSortAsc(!analyticsSortAsc)
        } else {
            setAnalyticsSortKey(key)
            setAnalyticsSortAsc(key === 'provider' || key === 'model' || key === 'voice_name')
        }
    }

    // --- Configuration state ---
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
    const [selectedTranscript, setSelectedTranscript] = useState(0)
    const [numRuns, setNumRuns] = useState(1)
    const [editingIdx, setEditingIdx] = useState<number | null>(null)
    const [editingText, setEditingText] = useState('')

    // --- AI sample generation ---
    const [aiScenario, setAiScenario] = useState('')
    const [showAiGenerate, setShowAiGenerate] = useState(false)
    const [selectedBundleId, setSelectedBundleId] = useState('')
    const [aiSampleCount, setAiSampleCount] = useState(5)

    const [customVoiceProvider, setCustomVoiceProvider] = useState('')
    const [customVoiceId, setCustomVoiceId] = useState('')
    const [customVoiceName, setCustomVoiceName] = useState('')
    const [customVoiceGender, setCustomVoiceGender] = useState('')
    const [customVoiceAccent, setCustomVoiceAccent] = useState('')
    const [customVoiceDescription, setCustomVoiceDescription] = useState('')
    const [editingCustomVoiceId, setEditingCustomVoiceId] = useState<string | null>(null)

    const bundlesWithLLM = voiceBundles.filter(
        (b) => b.llm_provider && b.llm_model
    )

    const generateSamplesMutation = useMutation({
        mutationFn: (params: { voice_bundle_id?: string; scenario?: string; count?: number }) =>
            apiClient.generateSampleTexts(params),
        onSuccess: (data) => {
            setSampleTexts(prev => [...prev, ...data.samples])
            setShowAiGenerate(false)
            setAiScenario('')
        },
    })

    // --- Active comparison ---
    const [activeComparisonId, setActiveComparisonId] = useState<string | null>(null)
    const [step, setStep] = useState<'configure' | 'progress' | 'blind-test' | 'results'>('configure')

    // --- Blind test state ---
    const [blindChoices, setBlindChoices] = useState<Record<number, 'A' | 'B'>>({})
    const [blindPairs, setBlindPairs] = useState<Array<{ sampleIdx: number; sampleA: TTSSample; sampleB: TTSSample; flipped: boolean }>>([])

    // --- Polling for active comparison ---
    const { data: comparison, refetch: refetchComparison } = useQuery<TTSComparison>({
        queryKey: ['tts-comparison', activeComparisonId],
        queryFn: () => apiClient.getTTSComparison(activeComparisonId!),
        enabled: !!activeComparisonId,
        refetchInterval: activeComparisonId && (step === 'progress') ? 3000 : false,
    })

    // --- Fetch viewed past comparison (for Past Simulations tab) ---
    const { data: viewedComparison, isLoading: viewedLoading } = useQuery<TTSComparison>({
        queryKey: ['tts-comparison', viewingPastId],
        queryFn: () => apiClient.getTTSComparison(viewingPastId!),
        enabled: !!viewingPastId,
    })

    // Transition from progress to blind-test or results when generation/evaluation completes
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
            } else if (comparison.status === 'failed') {
                // stay on progress to show error
            }
        }
    }, [comparison, step])

    // voice/model lists are consumed by ProviderPanel sub-components via the providers array

    // --- Mutations ---
    const createMutation = useMutation({
        mutationFn: async () => {
            const payload: {
                provider_a: string
                model_a: string
                voices_a: Array<{ id: string; name: string; sample_rate_hz?: number }>
                provider_b?: string
                model_b?: string
                voices_b?: Array<{ id: string; name: string; sample_rate_hz?: number }>
                sample_texts: string[]
                num_runs: number
            } = {
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
            // Refetch to get updated summary
            await refetchComparison()
        },
        onSuccess: () => {
            setStep('results')
        },
    })

    // --- Build blind test pairs ---
    function buildBlindPairs(comp: TTSComparison) {
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
    }

    const deleteMutation = useMutation({
        mutationFn: (id: string) => apiClient.deleteTTSComparison(id),
        onSuccess: (_data, id) => {
            setSelectedSimIds(prev => { const next = new Set(prev); next.delete(id); return next })
            refetchPast()
        },
    })

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
            setCustomVoiceId('')
            setCustomVoiceName('')
            setCustomVoiceGender('')
            setCustomVoiceAccent('')
            setCustomVoiceDescription('')
            await Promise.all([refetchCustomVoices(), refetchProviders()])
        },
    })

    const updateCustomVoiceMutation = useMutation({
        mutationFn: (voiceId: string) => apiClient.updateCustomTTSVoice(voiceId, {
            name: customVoiceName,
            gender: customVoiceGender,
            accent: customVoiceAccent,
            description: customVoiceDescription,
        }),
        onSuccess: async () => {
            setEditingCustomVoiceId(null)
            setCustomVoiceId('')
            setCustomVoiceName('')
            setCustomVoiceGender('')
            setCustomVoiceAccent('')
            setCustomVoiceDescription('')
            await Promise.all([refetchCustomVoices(), refetchProviders()])
        },
    })

    const deleteCustomVoiceMutation = useMutation({
        mutationFn: (voiceId: string) => apiClient.deleteCustomTTSVoice(voiceId),
        onSuccess: async () => {
            await Promise.all([refetchCustomVoices(), refetchProviders()])
        },
    })

    // --- Simulation selection for bulk actions ---
    const [selectedSimIds, setSelectedSimIds] = useState<Set<string>>(new Set())

    const allSimsSelected = pastComparisons.length > 0 && selectedSimIds.size === pastComparisons.length
    const someSimsSelected = selectedSimIds.size > 0

    function toggleSimSelection(id: string) {
        setSelectedSimIds(prev => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }

    function toggleAllSims() {
        if (allSimsSelected) {
            setSelectedSimIds(new Set())
        } else {
            setSelectedSimIds(new Set(pastComparisons.map(pc => pc.id)))
        }
    }

    const bulkDeleteMutation = useMutation({
        mutationFn: async (ids: string[]) => {
            for (const id of ids) {
                await apiClient.deleteTTSComparison(id)
            }
        },
        onSuccess: () => {
            setSelectedSimIds(new Set())
            refetchPast()
        },
    })

    const canRun = providerA && modelA && selectedVoicesA.length > 0 && sampleTexts.length > 0 &&
        (!enableComparison || (providerB && modelB && selectedVoicesB.length > 0))
    const canSaveCustomVoice = customVoiceProvider && customVoiceId.trim() && customVoiceName.trim()
    const providerOptionsForVoices = providers.map(p => p.provider)

    function startEditingCustomVoice(voice: CustomTTSVoice) {
        setEditingCustomVoiceId(voice.id)
        setCustomVoiceProvider(voice.provider)
        setCustomVoiceId(voice.voice_id)
        setCustomVoiceName(voice.name)
        setCustomVoiceGender(voice.gender === 'Unknown' ? '' : voice.gender)
        setCustomVoiceAccent(voice.accent === 'Unknown' ? '' : voice.accent)
        setCustomVoiceDescription(voice.description || '')
    }

    function resetCustomVoiceForm() {
        setEditingCustomVoiceId(null)
        setCustomVoiceProvider('')
        setCustomVoiceId('')
        setCustomVoiceName('')
        setCustomVoiceGender('')
        setCustomVoiceAccent('')
        setCustomVoiceDescription('')
    }

    function resetPlayground() {
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
        setActiveComparisonId(null)
        setStep('configure')
        setBlindChoices({})
        setBlindPairs([])
    }

    // --- Progress stats ---
    const totalSamples = comparison?.samples?.length || 0
    const completedSamples = comparison?.samples?.filter(s => s.status === 'completed').length || 0
    const failedSamples = comparison?.samples?.filter(s => s.status === 'failed').length || 0
    const progressPct = totalSamples > 0 ? Math.round(((completedSamples + failedSamples) / totalSamples) * 100) : 0

    // ============ RENDER ============

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
                        <Mic className="w-8 h-8 text-primary-600" />
                        Voice Playground
                    </h1>
                    <p className="mt-2 text-sm text-gray-600">
                        A/B test TTS providers &mdash; compare voice quality with real synthesis, blind tests, and automated evaluation
                    </p>
                </div>
                {step !== 'configure' && activeTab === 'playground' && (
                    <Button variant="ghost" onClick={resetPlayground} leftIcon={<RotateCcw className="w-4 h-4" />}>
                        New Comparison
                    </Button>
                )}
            </div>

            {/* Tabs */}
            <div className="border-b border-gray-200">
                <nav className="-mb-px flex space-x-8">
                    <button
                        onClick={() => { setActiveTab('playground'); setViewingPastId(null) }}
                        className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                            activeTab === 'playground'
                                ? 'border-primary-600 text-primary-600'
                                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                        }`}
                    >
                        <Mic className="w-4 h-4" />
                        Playground
                    </button>
                    <button
                        onClick={() => { setActiveTab('voices'); setViewingPastId(null) }}
                        className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                            activeTab === 'voices'
                                ? 'border-primary-600 text-primary-600'
                                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                        }`}
                    >
                        <Headphones className="w-4 h-4" />
                        Voices
                        {customVoices.length > 0 && (
                            <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
                                {customVoices.length}
                            </span>
                        )}
                    </button>
                    <button
                        onClick={() => { setActiveTab('past-simulations'); setViewingPastId(null) }}
                        className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                            activeTab === 'past-simulations'
                                ? 'border-primary-600 text-primary-600'
                                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                        }`}
                    >
                        <History className="w-4 h-4" />
                        Past Simulations
                        {pastComparisons.length > 0 && (
                            <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
                                {pastComparisons.length}
                            </span>
                        )}
                    </button>
                </nav>
            </div>

            {/* =========== TAB: PLAYGROUND =========== */}
            {activeTab === 'playground' && (
                <>
                    {/* =========== STEP: CONFIGURE =========== */}
                    {step === 'configure' && (
                        <>
                            {/* Sample Texts */}
                            <div className="bg-gradient-to-r from-indigo-50 to-violet-50 rounded-xl p-4 border border-indigo-100">
                                <div className="flex items-center gap-2 mb-3">
                                    <FileText className="w-5 h-5 text-indigo-600" />
                                    <h3 className="font-semibold text-indigo-900">Sample Transcripts</h3>
                                </div>
                                <div className="flex gap-2 flex-wrap mb-3">
                                    {DEFAULT_SAMPLE_TEXTS.map((t, idx) => {
                                        const isActive = sampleTexts.includes(t)
                                        return (
                                            <button
                                                key={idx}
                                                onClick={() => {
                                                    if (isActive) {
                                                        setSampleTexts(sampleTexts.filter(s => s !== t))
                                                    } else {
                                                        setSampleTexts([...sampleTexts, t])
                                                    }
                                                    setSelectedTranscript(idx)
                                                }}
                                                className={`px-3 py-2 text-xs rounded-lg transition-all ${isActive ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-indigo-100 border border-indigo-200'}`}
                                            >
                                                Sample {idx + 1}
                                            </button>
                                        )
                                    })}
                                </div>
                                <p className="p-3 bg-white rounded-lg text-sm text-gray-700 italic border border-indigo-100">
                                    &ldquo;{DEFAULT_SAMPLE_TEXTS[selectedTranscript]}&rdquo;
                                </p>
                                {/* Custom text + AI generate */}
                                <div className="mt-3 flex gap-2">
                                    <input
                                        type="text"
                                        value={customText}
                                        onChange={e => setCustomText(e.target.value)}
                                        placeholder="Add custom text..."
                                        className="flex-1 px-3 py-2 text-sm border border-indigo-200 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        onKeyDown={e => {
                                            if (e.key === 'Enter' && customText.trim()) {
                                                setSampleTexts([...sampleTexts, customText.trim()])
                                                setCustomText('')
                                            }
                                        }}
                                    />
                                    <button
                                        onClick={() => {
                                            if (customText.trim()) {
                                                setSampleTexts([...sampleTexts, customText.trim()])
                                                setCustomText('')
                                            }
                                        }}
                                        disabled={!customText.trim()}
                                        className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                                    >
                                        Add
                                    </button>
                                    <button
                                        onClick={() => setShowAiGenerate(!showAiGenerate)}
                                        className={`px-4 py-2 text-sm rounded-lg flex items-center gap-1.5 transition-all ${
                                            showAiGenerate
                                                ? 'bg-primary-600 text-white'
                                                : 'bg-primary-100 text-primary-700 hover:bg-primary-200 border border-primary-400'
                                        }`}
                                    >
                                        <Sparkles className="w-3.5 h-3.5" />
                                        AI Generate
                                    </button>
                                </div>

                                {/* AI Generate panel */}
                                {showAiGenerate && (
                                    <div className="mt-3 p-4 bg-primary-50 rounded-lg border border-primary-300">
                                        <div className="flex items-center gap-2 mb-2">
                                            <Sparkles className="w-4 h-4 text-primary-600" />
                                            <span className="text-sm font-medium text-primary-900">Generate samples with AI</span>
                                        </div>
                                        <p className="text-xs text-primary-700 mb-3">
                                            Pick an LLM provider, describe a scenario, and generate realistic TTS sample texts.
                                        </p>

                                        {/* LLM provider selector — shows provider/model from bundles */}
                                        <div className="mb-3">
                                            <label className="block text-xs font-medium text-primary-800 mb-1">
                                                <Bot className="w-3.5 h-3.5 inline mr-1" />
                                                LLM Provider
                                            </label>
                                            <select
                                                value={selectedBundleId}
                                                onChange={e => setSelectedBundleId(e.target.value)}
                                                className="w-full px-3 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                                            >
                                                <option value="">Select LLM provider...</option>
                                                {bundlesWithLLM.map(b => (
                                                    <option key={b.id} value={b.id}>
                                                        {getProviderInfo(b.llm_provider || '').label} / {b.llm_model}
                                                    </option>
                                                ))}
                                            </select>
                                            {bundlesWithLLM.length === 0 && (
                                                <p className="mt-1 text-xs text-primary-600">
                                                    No voice bundles with LLM configured. Create one in Voice Bundles first.
                                                </p>
                                            )}
                                        </div>

                                        {/* Scenario + Count */}
                                        <div className="flex gap-2 mb-3">
                                            <input
                                                type="text"
                                                value={aiScenario}
                                                onChange={e => setAiScenario(e.target.value)}
                                                placeholder="e.g. Healthcare appointment reminders, Bank customer support..."
                                                className="flex-1 px-3 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                                                onKeyDown={e => {
                                                    if (e.key === 'Enter' && !generateSamplesMutation.isPending && selectedBundleId) {
                                                        generateSamplesMutation.mutate({
                                                            voice_bundle_id: selectedBundleId,
                                                            scenario: aiScenario || undefined,
                                                            count: aiSampleCount,
                                                        })
                                                    }
                                                }}
                                            />
                                            <div className="flex items-center gap-1">
                                                <label className="text-xs text-primary-800 whitespace-nowrap">Count:</label>
                                                <select
                                                    value={aiSampleCount}
                                                    onChange={e => setAiSampleCount(Number(e.target.value))}
                                                    className="px-2 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                                                >
                                                    {[3, 5, 8, 10].map(n => (
                                                        <option key={n} value={n}>{n}</option>
                                                    ))}
                                                </select>
                                            </div>
                                        </div>

                                        <div className="flex justify-end">
                                            <button
                                                onClick={() => generateSamplesMutation.mutate({
                                                    voice_bundle_id: selectedBundleId || undefined,
                                                    scenario: aiScenario || undefined,
                                                    count: aiSampleCount,
                                                })}
                                                disabled={generateSamplesMutation.isPending || !selectedBundleId}
                                                className="px-4 py-2 text-sm bg-primary-100 text-primary-700 border border-primary-400 rounded-lg hover:bg-primary-200 disabled:opacity-60 flex items-center gap-1.5"
                                            >
                                                {generateSamplesMutation.isPending
                                                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...</>
                                                    : <><Sparkles className="w-3.5 h-3.5" /> Generate Samples</>
                                                }
                                            </button>
                                        </div>

                                        {generateSamplesMutation.isError && (
                                            <p className="mt-2 text-xs text-red-600">
                                                {(generateSamplesMutation.error as any)?.response?.data?.detail || 'Failed to generate samples'}
                                            </p>
                                        )}
                                    </div>
                                )}

                                {/* Active sample texts — editable list */}
                                {sampleTexts.length > 0 && (
                                    <div className="mt-3 space-y-1.5">
                                        {sampleTexts.map((t, idx) => (
                                            <div key={idx} className="group flex items-start gap-2 bg-white rounded-lg border border-indigo-200 px-3 py-2">
                                                <span className="flex-shrink-0 w-5 h-5 rounded bg-indigo-100 text-indigo-600 flex items-center justify-center text-[10px] font-bold mt-0.5">
                                                    {idx + 1}
                                                </span>
                                                {editingIdx === idx ? (
                                                    <textarea
                                                        autoFocus
                                                        value={editingText}
                                                        onChange={e => setEditingText(e.target.value)}
                                                        onKeyDown={e => {
                                                            if (e.key === 'Enter' && !e.shiftKey) {
                                                                e.preventDefault()
                                                                if (editingText.trim()) {
                                                                    setSampleTexts(sampleTexts.map((s, i) => i === idx ? editingText.trim() : s))
                                                                }
                                                                setEditingIdx(null)
                                                            }
                                                            if (e.key === 'Escape') {
                                                                setEditingIdx(null)
                                                            }
                                                        }}
                                                        className="flex-1 text-sm text-gray-800 bg-indigo-50 border border-indigo-300 rounded px-2 py-1 focus:ring-2 focus:ring-indigo-500 focus:outline-none resize-none min-h-[2.25rem]"
                                                        rows={2}
                                                    />
                                                ) : (
                                                    <span className="flex-1 text-sm text-gray-700 leading-snug pt-0.5">
                                                        {t}
                                                    </span>
                                                )}
                                                <div className="flex items-center gap-0.5 flex-shrink-0 mt-0.5">
                                                    {editingIdx === idx ? (
                                                        <button
                                                            onClick={() => {
                                                                if (editingText.trim()) {
                                                                    setSampleTexts(sampleTexts.map((s, i) => i === idx ? editingText.trim() : s))
                                                                }
                                                                setEditingIdx(null)
                                                            }}
                                                            className="p-1 rounded hover:bg-green-100 text-green-600 transition-colors"
                                                            title="Save"
                                                        >
                                                            <Check className="w-3.5 h-3.5" />
                                                        </button>
                                                    ) : (
                                                        <button
                                                            onClick={() => {
                                                                setEditingIdx(idx)
                                                                setEditingText(t)
                                                            }}
                                                            className="p-1 rounded hover:bg-indigo-100 text-gray-400 hover:text-indigo-600 transition-colors opacity-0 group-hover:opacity-100"
                                                            title="Edit"
                                                        >
                                                            <Pencil className="w-3.5 h-3.5" />
                                                        </button>
                                                    )}
                                                    <button
                                                        onClick={() => {
                                                            setSampleTexts(sampleTexts.filter((_, i) => i !== idx))
                                                            if (editingIdx === idx) setEditingIdx(null)
                                                        }}
                                                        className="p-1 rounded hover:bg-red-100 text-gray-400 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                                                        title="Remove"
                                                    >
                                                        <X className="w-3.5 h-3.5" />
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Number of Runs */}
                            <div className="bg-white rounded-xl shadow-sm p-4 border border-gray-100 flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <Hash className="w-5 h-5 text-gray-500" />
                                    <div>
                                        <p className="font-medium text-gray-900 text-sm">Number of Runs</p>
                                        <p className="text-xs text-gray-500">
                                            Repeat each voice+text combination. Total evaluations = samples x selected voices x runs.
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
                                            {/* Provider A */}
                                            <ProviderPanel
                                                label="A"
                                                color="blue"
                                                providers={providers}
                                                selectedProvider={providerA}
                                                selectedModel={modelA}
                                                selectedVoices={selectedVoicesA}
                                                sampleRate={sampleRateA}
                                                onProviderChange={p => { setProviderA(p); setModelA(''); setSelectedVoicesA([]); setSampleRateA(null) }}
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

                                                    {/* Provider B */}
                                                    <ProviderPanel
                                                        label="B"
                                                        color="purple"
                                                        providers={providers}
                                                        selectedProvider={providerB}
                                                        selectedModel={modelB}
                                                        selectedVoices={selectedVoicesB}
                                                        sampleRate={sampleRateB}
                                                        onProviderChange={p => { setProviderB(p); setModelB(''); setSelectedVoicesB([]); setSampleRateB(null) }}
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
                                                onClick={() => createMutation.mutate()}
                                                disabled={!canRun || createMutation.isPending}
                                                leftIcon={createMutation.isPending ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
                                                className="px-12"
                                            >
                                                {createMutation.isPending ? 'Starting...' : (enableComparison ? 'Run Comparison' : 'Run Benchmark')}
                                            </Button>
                                        </div>
                                        {createMutation.isError && (
                                            <p className="text-sm text-red-600 text-center mt-3">
                                                {(createMutation.error as any)?.response?.data?.detail || 'Failed to start comparison'}
                                            </p>
                                        )}
                                    </>
                                )}
                            </div>
                        </>
                    )}

            {/* =========== STEP: PROGRESS =========== */}
            {step === 'progress' && comparison && (
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
                                {hasSecondProvider(comparison) && (
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
                            <span>{comparison.status === 'generating' ? 'Generating audio...' : comparison.status === 'evaluating' ? 'Evaluating quality...' : comparison.status === 'completed' ? 'Complete' : 'Processing...'}</span>
                            <span>{completedSamples}/{totalSamples} samples</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-3">
                            <div
                                className="bg-gradient-to-r from-blue-500 to-purple-500 h-3 rounded-full transition-all duration-500"
                                style={{ width: `${progressPct}%` }}
                            />
                        </div>
                    </div>

                    {/* Per-sample status */}
                    {(() => { const hzMaps = buildVoiceHzMaps(comparison); return (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                        {comparison.samples.map(s => {
                            const isA = s.side ? s.side === 'A' : (s.provider === comparison.provider_a && s.model === comparison.model_a)
                            const hz = isA ? hzMaps.a[s.voice_id] : hzMaps.b[s.voice_id]
                            return (
                            <div key={s.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg text-xs">
                                {s.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />}
                                {s.status === 'generating' && <Loader2 className="w-3.5 h-3.5 text-yellow-500 animate-spin flex-shrink-0" />}
                                {s.status === 'pending' && <Clock className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />}
                                {s.status === 'failed' && <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />}
                                <span className="truncate text-gray-700">{s.voice_name || s.voice_id}</span>
                                <HzBadge hz={hz} />
                                {s.ttfb_ms != null && <span className="text-gray-400 ml-auto" title="Time-to-first-byte">{Math.round(s.ttfb_ms)}ms</span>}
                                {s.ttfb_ms == null && s.latency_ms != null && <span className="text-gray-400 ml-auto">{Math.round(s.latency_ms)}ms</span>}
                            </div>
                            )
                        })}
                    </div>
                    ); })()}

                    {comparison.status === 'failed' && (
                        <div className="p-4 bg-red-50 rounded-lg border border-red-200">
                            <p className="text-sm text-red-700">{comparison.error_message || 'Comparison failed'}</p>
                        </div>
                    )}
                </div>
            )}

            {/* =========== STEP: BLIND TEST =========== */}
            {step === 'blind-test' && comparison && (
                <div className="space-y-6">
                    <div className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl p-5 border border-amber-200">
                        <div className="flex items-center gap-3 mb-2">
                            <Headphones className="w-6 h-6 text-amber-600" />
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
                        <Button
                            variant="ghost"
                            onClick={() => setStep('results')}
                        >
                            Skip Blind Test
                        </Button>
                        <Button
                            variant="primary"
                            size="lg"
                            onClick={() => blindTestMutation.mutate()}
                            disabled={Object.keys(blindChoices).length === 0 || blindTestMutation.isPending}
                            leftIcon={blindTestMutation.isPending ? <Loader2 className="w-5 h-5 animate-spin" /> : <ArrowRight className="w-5 h-5" />}
                            className="px-10"
                        >
                            Submit &amp; View Results
                        </Button>
                    </div>
                </div>
            )}

            {/* =========== STEP: RESULTS =========== */}
            {step === 'results' && comparison && (
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
                                    {comparison.sample_texts?.length || 0} samples &middot; {comparison.samples?.length || 0} audio files
                                    {comparison.num_runs > 1 && <> &middot; {comparison.num_runs} runs</>}
                                </p>
                            </div>
                            <StatusBadge status={comparison.status} />
                        </div>

                        {/* Winner Banner */}
                        {hasSecondProvider(comparison) && comparison.evaluation_summary && (() => {
                            const sumA = comparison.evaluation_summary.provider_a || {}
                            const sumB = comparison.evaluation_summary.provider_b || {}
                            const mosA = sumA['MOS Score'] ?? 0
                            const mosB = sumB['MOS Score'] ?? 0
                            const bt = comparison.evaluation_summary.blind_test
                            const btScore = bt ? (bt.a_wins - bt.b_wins) : 0
                            const winner = (mosA + btScore * 0.1) >= (mosB) ? 'A' : 'B'
                            const winnerName = winner === 'A'
                                ? getProviderInfo(comparison.provider_a).label
                                : getProviderInfo(comparison.provider_b || '').label

                            return (
                                <div className="p-5 bg-gradient-to-r from-green-500 via-emerald-500 to-teal-500 rounded-xl text-white mb-6">
                                    <div className="flex items-center justify-center gap-3">
                                        <Trophy className="w-8 h-8" />
                                        <span className="text-xl font-bold">
                                            Recommended: {winnerName}
                                        </span>
                                    </div>
                                </div>
                            )
                        })()}

                        {/* Metrics Table */}
                        {comparison.evaluation_summary && (() => {
                            const sumA = comparison.evaluation_summary.provider_a || {}
                            const sumB = comparison.evaluation_summary.provider_b || {}
                            if (hasSecondProvider(comparison)) {
                                return (
                                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
                                        <MetricCard label="MOS Score" valueA={sumA['MOS Score']} valueB={sumB['MOS Score']} higherIsBetter />
                                        <MetricCard label="Valence" valueA={sumA['Valence']} valueB={sumB['Valence']} higherIsBetter />
                                        <MetricCard label="Arousal" valueA={sumA['Arousal']} valueB={sumB['Arousal']} higherIsBetter />
                                        <MetricCard label="Prosody" valueA={sumA['Prosody Score']} valueB={sumB['Prosody Score']} higherIsBetter />
                                        <MetricCard label="TTFB" valueA={sumA['avg_ttfb_ms']} valueB={sumB['avg_ttfb_ms']} unit="ms" higherIsBetter={false} />
                                        <MetricCard label="Total Latency" valueA={sumA['avg_latency_ms']} valueB={sumB['avg_latency_ms']} unit="ms" higherIsBetter={false} />
                                    </div>
                                )
                            }
                            return (
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-3 mb-6">
                                    <MetricCard label="MOS Score" valueA={sumA['MOS Score']} valueB={null} higherIsBetter />
                                    <MetricCard label="Valence" valueA={sumA['Valence']} valueB={null} higherIsBetter />
                                    <MetricCard label="Arousal" valueA={sumA['Arousal']} valueB={null} higherIsBetter />
                                    <MetricCard label="Prosody" valueA={sumA['Prosody Score']} valueB={null} higherIsBetter />
                                    <MetricCard label="TTFB" valueA={sumA['avg_ttfb_ms']} valueB={null} unit="ms" higherIsBetter={false} />
                                    <MetricCard label="Total Latency" valueA={sumA['avg_latency_ms']} valueB={null} unit="ms" higherIsBetter={false} />
                                </div>
                            )
                        })()}

                        {/* Blind Test Results */}
                        {comparison.evaluation_summary?.blind_test && (() => {
                            const bt = comparison.evaluation_summary.blind_test
                            return (
                                <div className="p-4 bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl border border-amber-200 mb-6">
                                    <h4 className="font-semibold text-amber-900 mb-3 flex items-center gap-2">
                                        <Headphones className="w-5 h-5" />
                                        Blind Test Results
                                    </h4>
                                    <div className="flex items-center gap-6">
                                        <div className="text-center flex flex-col items-center gap-1">
                                            <ProviderLogo provider={comparison.provider_a} size="sm" />
                                            <p className="text-xs text-gray-500">{getProviderInfo(comparison.provider_a).label}</p>
                                            <p className="text-2xl font-bold text-blue-600">{bt.a_pct}%</p>
                                            <p className="text-xs text-gray-400">{bt.a_wins} wins</p>
                                        </div>
                                        <span className="text-gray-300 text-xl">vs</span>
                                        <div className="text-center flex flex-col items-center gap-1">
                                            <ProviderLogo provider={comparison.provider_b || ''} size="sm" />
                                            <p className="text-xs text-gray-500">{getProviderInfo(comparison.provider_b || '').label}</p>
                                            <p className="text-2xl font-bold text-purple-600">{bt.b_pct}%</p>
                                            <p className="text-xs text-gray-400">{bt.b_wins} wins</p>
                                        </div>
                                    </div>
                                </div>
                            )
                        })()}

                        {/* Provider Labels */}
                        <div className="flex items-center justify-center gap-6 mb-4">
                            <div className="flex items-center gap-2">
                                <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">A</span>
                                <ProviderLogo provider={comparison.provider_a} size="sm" />
                                <span className="text-sm font-medium text-gray-700">
                                    {getProviderInfo(comparison.provider_a).label} ({comparison.model_a})
                                </span>
                            </div>
                            {hasSecondProvider(comparison) && (
                                <div className="flex items-center gap-2">
                                    <span className="w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center text-xs font-bold">B</span>
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
                        {(() => { const hzMaps = buildVoiceHzMaps(comparison); return (
                        <div className="space-y-3 max-h-[700px] overflow-y-auto">
                            {comparison.sample_texts?.map((text, idx) => (
                                <SampleGroup
                                    key={idx}
                                    sampleIndex={idx}
                                    text={text}
                                    samples={comparison.samples.filter(s => s.sample_index === idx)}
                                    providerA={comparison.provider_a}
                                    providerB={comparison.provider_b || undefined}
                                    playingId={playingId}
                                    onPlay={play}
                                    numRuns={comparison.num_runs || 1}
                                    hzMapA={hzMaps.a}
                                    hzMapB={hzMaps.b}
                                />
                            ))}
                        </div>
                        ); })()}
                    </div>

                    {/* Actions */}
                    <div className="flex justify-center">
                        <Button variant="primary" leftIcon={<RotateCcw className="w-4 h-4" />} onClick={resetPlayground}>
                            Run New Comparison
                        </Button>
                    </div>
                </div>
            )}
                </>
            )}

            {/* =========== TAB: VOICES =========== */}
            {activeTab === 'voices' && (
                <div className="space-y-6">
                    <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-100">
                        <h2 className="text-lg font-semibold text-gray-900 mb-1">Custom Voices</h2>
                        <p className="text-sm text-gray-500 mb-5">
                            Add provider-specific voice IDs so they can be selected during TTS comparison benchmarks.
                        </p>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
                                <select
                                    value={customVoiceProvider}
                                    onChange={e => setCustomVoiceProvider(e.target.value)}
                                    disabled={!!editingCustomVoiceId}
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-100"
                                >
                                    <option value="">Select provider...</option>
                                    {providerOptionsForVoices.map(provider => (
                                        <option key={provider} value={provider}>{getProviderInfo(provider).label}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Voice ID</label>
                                <input
                                    value={customVoiceId}
                                    onChange={e => setCustomVoiceId(e.target.value)}
                                    disabled={!!editingCustomVoiceId}
                                    placeholder="e.g. 21m00Tcm4TlvDq8ikWAM"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                                <input
                                    value={customVoiceName}
                                    onChange={e => setCustomVoiceName(e.target.value)}
                                    placeholder="e.g. My Sales Voice"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Gender (optional)</label>
                                <input
                                    value={customVoiceGender}
                                    onChange={e => setCustomVoiceGender(e.target.value)}
                                    placeholder="e.g. Female"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Accent (optional)</label>
                                <input
                                    value={customVoiceAccent}
                                    onChange={e => setCustomVoiceAccent(e.target.value)}
                                    placeholder="e.g. American"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
                                <input
                                    value={customVoiceDescription}
                                    onChange={e => setCustomVoiceDescription(e.target.value)}
                                    placeholder="e.g. Cloned from support lead"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                                />
                            </div>
                        </div>

                        <div className="mt-4 flex items-center gap-2">
                            <Button
                                variant="primary"
                                leftIcon={editingCustomVoiceId ? <Save className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
                                disabled={!canSaveCustomVoice || createCustomVoiceMutation.isPending || updateCustomVoiceMutation.isPending}
                                onClick={() => {
                                    if (editingCustomVoiceId) {
                                        updateCustomVoiceMutation.mutate(editingCustomVoiceId)
                                    } else {
                                        createCustomVoiceMutation.mutate()
                                    }
                                }}
                            >
                                {editingCustomVoiceId ? 'Save Voice' : 'Add Voice'}
                            </Button>
                            {editingCustomVoiceId && (
                                <Button variant="ghost" onClick={resetCustomVoiceForm}>Cancel Edit</Button>
                            )}
                        </div>

                        {(createCustomVoiceMutation.isError || updateCustomVoiceMutation.isError) && (
                            <p className="mt-3 text-sm text-red-600">
                                {((createCustomVoiceMutation.error || updateCustomVoiceMutation.error) as any)?.response?.data?.detail || 'Failed to save custom voice'}
                            </p>
                        )}
                    </div>

                    <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-100">
                        <h3 className="font-semibold text-gray-900 mb-4">Saved Custom Voices</h3>
                        {customVoices.length === 0 ? (
                            <p className="text-sm text-gray-500">No custom voices yet. Add one above to use it in Playground comparisons.</p>
                        ) : (
                            <div className="space-y-2">
                                {customVoices.map(cv => (
                                    <div key={cv.id} className="border border-gray-200 rounded-lg p-3 flex items-center justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="font-medium text-gray-900">{cv.name}</span>
                                                <span className="text-xs px-2 py-0.5 rounded-full bg-primary-100 text-primary-700">Custom</span>
                                                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 inline-flex items-center gap-1.5">
                                                    <ProviderLogo provider={cv.provider} size="sm" />
                                                    {getProviderInfo(cv.provider).label}
                                                </span>
                                            </div>
                                            <p className="text-xs text-gray-500 mt-1 font-mono break-all">Voice ID: {cv.voice_id}</p>
                                            <p className="text-xs text-gray-500 mt-1">{cv.gender} • {cv.accent}</p>
                                            {cv.description && <p className="text-xs text-gray-500 mt-1">{cv.description}</p>}
                                        </div>
                                        <div className="flex items-center gap-2 flex-shrink-0">
                                            <Button variant="ghost" onClick={() => startEditingCustomVoice(cv)}>Edit</Button>
                                            <Button
                                                variant="ghost"
                                                className="text-red-600 hover:text-red-700"
                                                disabled={deleteCustomVoiceMutation.isPending}
                                                onClick={() => {
                                                    setDeleteConfirm({
                                                        message: `Delete custom voice "${cv.name}" (${cv.voice_id})?`,
                                                        onConfirm: () => deleteCustomVoiceMutation.mutate(cv.id),
                                                    })
                                                }}
                                            >
                                                Delete
                                            </Button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* =========== TAB: PAST SIMULATIONS =========== */}
            {activeTab === 'past-simulations' && (
                <>
                    {/* Detail view for a specific comparison */}
                    {viewingPastId ? (
                        <div className="space-y-6">
                            {/* Back button */}
                            <button
                                onClick={() => { setViewingPastId(null); stop() }}
                                className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
                            >
                                <ArrowLeft className="w-4 h-4" />
                                Back to Past Simulations
                            </button>

                            {viewedLoading ? (
                                <div className="flex items-center justify-center py-16 text-gray-500">
                                    <Loader2 className="w-6 h-6 animate-spin mr-2" />
                                    Loading comparison...
                                </div>
                            ) : viewedComparison ? (
                                <>
                                    {/* Summary Header */}
                                    <div className="bg-white rounded-xl shadow-lg p-6">
                                        <div className="flex items-center justify-between mb-4">
                                            <div>
                                                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                                                    {viewedComparison.simulation_id && (
                                                        <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs font-mono rounded border border-gray-200">
                                                            #{viewedComparison.simulation_id}
                                                        </span>
                                                    )}
                                                    {viewedComparison.name}
                                                </h2>
                                                <p className="text-sm text-gray-500">
                                                    {viewedComparison.sample_texts?.length || 0} samples &middot; {viewedComparison.samples?.length || 0} audio files
                                                    {viewedComparison.num_runs > 1 && <> &middot; {viewedComparison.num_runs} runs</>}
                                                </p>
                                            </div>
                                            <StatusBadge status={viewedComparison.status} />
                                        </div>

                                        {/* Winner Banner */}
                                        {hasSecondProvider(viewedComparison) && viewedComparison.evaluation_summary && (() => {
                                            const sumA = viewedComparison.evaluation_summary.provider_a || {}
                                            const sumB = viewedComparison.evaluation_summary.provider_b || {}
                                            const mosA = sumA['MOS Score'] ?? 0
                                            const mosB = sumB['MOS Score'] ?? 0
                                            const bt = viewedComparison.evaluation_summary.blind_test
                                            const btScore = bt ? (bt.a_wins - bt.b_wins) : 0
                                            const winner = (mosA + btScore * 0.1) >= (mosB) ? 'A' : 'B'
                                            const winnerName = winner === 'A'
                                                ? getProviderInfo(viewedComparison.provider_a).label
                                                : getProviderInfo(viewedComparison.provider_b || '').label

                                            return (
                                                <div className="p-5 bg-gradient-to-r from-green-500 via-emerald-500 to-teal-500 rounded-xl text-white mb-6">
                                                    <div className="flex items-center justify-center gap-3">
                                                        <Trophy className="w-8 h-8" />
                                                        <span className="text-xl font-bold">
                                                            Recommended: {winnerName}
                                                        </span>
                                                    </div>
                                                </div>
                                            )
                                        })()}

                                        {/* Metrics Table */}
                                        {viewedComparison.evaluation_summary && (() => {
                                            const sumA = viewedComparison.evaluation_summary.provider_a || {}
                                            const sumB = viewedComparison.evaluation_summary.provider_b || {}
                                            if (hasSecondProvider(viewedComparison)) {
                                                return (
                                                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
                                                        <MetricCard label="MOS Score" valueA={sumA['MOS Score']} valueB={sumB['MOS Score']} higherIsBetter />
                                                        <MetricCard label="Valence" valueA={sumA['Valence']} valueB={sumB['Valence']} higherIsBetter />
                                                        <MetricCard label="Arousal" valueA={sumA['Arousal']} valueB={sumB['Arousal']} higherIsBetter />
                                                        <MetricCard label="Prosody" valueA={sumA['Prosody Score']} valueB={sumB['Prosody Score']} higherIsBetter />
                                                        <MetricCard label="TTFB" valueA={sumA['avg_ttfb_ms']} valueB={sumB['avg_ttfb_ms']} unit="ms" higherIsBetter={false} />
                                                        <MetricCard label="Total Latency" valueA={sumA['avg_latency_ms']} valueB={sumB['avg_latency_ms']} unit="ms" higherIsBetter={false} />
                                                    </div>
                                                )
                                            }
                                            return (
                                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-3 mb-6">
                                                    <MetricCard label="MOS Score" valueA={sumA['MOS Score']} valueB={null} higherIsBetter />
                                                    <MetricCard label="Valence" valueA={sumA['Valence']} valueB={null} higherIsBetter />
                                                    <MetricCard label="Arousal" valueA={sumA['Arousal']} valueB={null} higherIsBetter />
                                                    <MetricCard label="Prosody" valueA={sumA['Prosody Score']} valueB={null} higherIsBetter />
                                                    <MetricCard label="TTFB" valueA={sumA['avg_ttfb_ms']} valueB={null} unit="ms" higherIsBetter={false} />
                                                    <MetricCard label="Total Latency" valueA={sumA['avg_latency_ms']} valueB={null} unit="ms" higherIsBetter={false} />
                                                </div>
                                            )
                                        })()}

                                        {/* Blind Test Results */}
                                        {viewedComparison.evaluation_summary?.blind_test && (() => {
                                            const bt = viewedComparison.evaluation_summary.blind_test
                                            return (
                                                <div className="p-4 bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl border border-amber-200 mb-6">
                                                    <h4 className="font-semibold text-amber-900 mb-3 flex items-center gap-2">
                                                        <Headphones className="w-5 h-5" />
                                                        Blind Test Results
                                                    </h4>
                                                    <div className="flex items-center gap-6">
                                                        <div className="text-center flex flex-col items-center gap-1">
                                                            <ProviderLogo provider={viewedComparison.provider_a} size="sm" />
                                                            <p className="text-xs text-gray-500">{getProviderInfo(viewedComparison.provider_a).label}</p>
                                                            <p className="text-2xl font-bold text-blue-600">{bt.a_pct}%</p>
                                                            <p className="text-xs text-gray-400">{bt.a_wins} wins</p>
                                                        </div>
                                                        <span className="text-gray-300 text-xl">vs</span>
                                                        <div className="text-center flex flex-col items-center gap-1">
                                                            <ProviderLogo provider={viewedComparison.provider_b || ''} size="sm" />
                                                            <p className="text-xs text-gray-500">{getProviderInfo(viewedComparison.provider_b || '').label}</p>
                                                            <p className="text-2xl font-bold text-purple-600">{bt.b_pct}%</p>
                                                            <p className="text-xs text-gray-400">{bt.b_wins} wins</p>
                                                        </div>
                                                    </div>
                                                </div>
                                            )
                                        })()}

                                        {/* Provider Labels */}
                                        <div className="flex items-center justify-center gap-6 mb-4">
                                            <div className="flex items-center gap-2">
                                                <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">A</span>
                                                <ProviderLogo provider={viewedComparison.provider_a} size="sm" />
                                                <span className="text-sm font-medium text-gray-700">
                                                    {getProviderInfo(viewedComparison.provider_a).label} ({viewedComparison.model_a})
                                                </span>
                                            </div>
                                            {hasSecondProvider(viewedComparison) && (
                                                <div className="flex items-center gap-2">
                                                    <span className="w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center text-xs font-bold">B</span>
                                                    <ProviderLogo provider={viewedComparison.provider_b || ''} size="sm" />
                                                    <span className="text-sm font-medium text-gray-700">
                                                        {getProviderInfo(viewedComparison.provider_b || '').label} ({viewedComparison.model_b})
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
                                        {(() => { const hzMaps = buildVoiceHzMaps(viewedComparison); return (
                                        <div className="space-y-3 max-h-[700px] overflow-y-auto">
                                            {viewedComparison.sample_texts?.map((text, idx) => (
                                                <SampleGroup
                                                    key={idx}
                                                    sampleIndex={idx}
                                                    text={text}
                                                    samples={viewedComparison.samples.filter(s => s.sample_index === idx)}
                                                    providerA={viewedComparison.provider_a}
                                                    providerB={viewedComparison.provider_b || undefined}
                                                    playingId={playingId}
                                                    onPlay={play}
                                                    numRuns={viewedComparison.num_runs || 1}
                                                    hzMapA={hzMaps.a}
                                                    hzMapB={hzMaps.b}
                                                />
                                            ))}
                                        </div>
                                        ); })()}
                                    </div>

                                    {/* Back action */}
                                    <div className="flex justify-center">
                                        <button
                                            onClick={() => { setViewingPastId(null); stop() }}
                                            className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                                        >
                                            <ArrowLeft className="w-4 h-4" />
                                            Back to All Simulations
                                        </button>
                                    </div>
                                </>
                            ) : (
                                <div className="text-center py-16 text-gray-500">
                                    Comparison not found.
                                    <button onClick={() => setViewingPastId(null)} className="ml-2 text-primary-600 hover:underline">
                                        Go back
                                    </button>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {/* Sub-view toggle: Simulations | Analytics */}
                            <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1 w-fit">
                                <button
                                    onClick={() => setPastSubView('simulations')}
                                    className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                                        pastSubView === 'simulations'
                                            ? 'bg-white text-gray-900 shadow-sm'
                                            : 'text-gray-500 hover:text-gray-700'
                                    }`}
                                >
                                    <History className="w-4 h-4" />
                                    Simulations
                                </button>
                                <button
                                    onClick={() => setPastSubView('analytics')}
                                    className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                                        pastSubView === 'analytics'
                                            ? 'bg-white text-gray-900 shadow-sm'
                                            : 'text-gray-500 hover:text-gray-700'
                                    }`}
                                >
                                    <BarChart3 className="w-4 h-4" />
                                    Analytics
                                </button>
                            </div>

                            {/* ---- Simulations list ---- */}
                            {pastSubView === 'simulations' && (
                                <div className="bg-white rounded-xl shadow-lg p-6">
                                    <div className="flex items-center gap-2 mb-4">
                                        <History className="w-5 h-5 text-gray-600" />
                                        <h2 className="text-lg font-semibold text-gray-900">Past Simulations</h2>
                                        <span className="ml-auto text-xs text-gray-400">{pastComparisons.length} comparison{pastComparisons.length !== 1 ? 's' : ''}</span>
                                    </div>
                                    {pastComparisons.length === 0 ? (
                                        <div className="text-center py-16">
                                            <History className="w-12 h-12 mx-auto text-gray-300 mb-3" />
                                            <p className="text-gray-600 font-medium">No simulations yet</p>
                                            <p className="text-sm text-gray-500 mt-1">Run a comparison from the Playground tab to see results here.</p>
                                            <button
                                                onClick={() => setActiveTab('playground')}
                                                className="mt-4 inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-primary-600 bg-primary-50 rounded-lg hover:bg-primary-100 transition-colors"
                                            >
                                                <Play className="w-4 h-4" />
                                                Go to Playground
                                            </button>
                                        </div>
                                    ) : (
                                        <>
                                            {/* Bulk actions toolbar */}
                                            <div className="flex items-center gap-3 mb-3">
                                                <label className="flex items-center gap-2 cursor-pointer select-none">
                                                    <input
                                                        type="checkbox"
                                                        checked={allSimsSelected}
                                                        ref={el => { if (el) el.indeterminate = someSimsSelected && !allSimsSelected }}
                                                        onChange={toggleAllSims}
                                                        className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                                    />
                                                    <span className="text-xs text-gray-600">
                                                        {allSimsSelected ? 'Deselect all' : 'Select all'}
                                                    </span>
                                                </label>
                                                {someSimsSelected && (
                                                    <div className="flex items-center gap-2 ml-auto">
                                                        <span className="text-xs text-gray-500">{selectedSimIds.size} selected</span>
                                                        <button
                                                            onClick={() => {
                                                                setDeleteConfirm({
                                                                    message: `Delete ${selectedSimIds.size} comparison${selectedSimIds.size > 1 ? 's' : ''} and all their audio samples?`,
                                                                    onConfirm: () => bulkDeleteMutation.mutate(Array.from(selectedSimIds)),
                                                                })
                                                            }}
                                                            disabled={bulkDeleteMutation.isPending}
                                                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-60 transition-colors"
                                                        >
                                                            {bulkDeleteMutation.isPending
                                                                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                                                : <Trash2 className="w-3.5 h-3.5" />
                                                            }
                                                            Delete selected
                                                        </button>
                                                    </div>
                                                )}
                                            </div>

                                            <div className="space-y-2">
                                                {pastComparisons.map(pc => {
                                                    const isSelected = selectedSimIds.has(pc.id)
                                                    return (
                                                        <div
                                                            key={pc.id}
                                                            onClick={() => setViewingPastId(pc.id)}
                                                            className={`flex items-center gap-3 p-3 rounded-lg border transition-colors cursor-pointer group ${
                                                                isSelected
                                                                    ? 'bg-primary-50 border-primary-300'
                                                                    : 'bg-gray-50 border-gray-100 hover:bg-gray-100'
                                                            }`}
                                                        >
                                                            <input
                                                                type="checkbox"
                                                                checked={isSelected}
                                                                onChange={(e) => { e.stopPropagation(); toggleSimSelection(pc.id) }}
                                                                onClick={(e) => e.stopPropagation()}
                                                                className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 flex-shrink-0"
                                                            />
                                                            <div className="flex items-center gap-2 flex-shrink-0">
                                                                <ProviderLogo provider={pc.provider_a} size="sm" />
                                                                {hasSecondProvider(pc) ? (
                                                                    <>
                                                                        <span className="text-xs text-gray-400">vs</span>
                                                                        <ProviderLogo provider={pc.provider_b || ''} size="sm" />
                                                                    </>
                                                                ) : (
                                                                    <span className="text-[10px] text-gray-500 px-2 py-0.5 bg-gray-200 rounded-full">Single</span>
                                                                )}
                                                            </div>
                                                            <div className="flex-1 min-w-0">
                                                                <div className="flex items-center gap-2">
                                                                    {pc.simulation_id && (
                                                                        <span className="px-1.5 py-0.5 bg-gray-200 text-gray-700 text-[10px] font-mono font-medium rounded">
                                                                            #{pc.simulation_id}
                                                                        </span>
                                                                    )}
                                                                    <p className="text-sm font-medium text-gray-800 truncate">{pc.name}</p>
                                                                </div>
                                                                <p className="text-xs text-gray-500">
                                                                    {hasSecondProvider(pc)
                                                                        ? `${getProviderInfo(pc.provider_a).label} vs ${getProviderInfo(pc.provider_b || '').label}`
                                                                        : `${getProviderInfo(pc.provider_a).label} benchmark`}
                                                                    {' '}&middot; {pc.sample_count} sample{pc.sample_count !== 1 ? 's' : ''}
                                                                    {pc.num_runs > 1 && <> &middot; {pc.num_runs} runs</>}
                                                                    {' '}&middot; {new Date(pc.created_at).toLocaleDateString()}
                                                                </p>
                                                            </div>
                                                            <StatusBadge status={pc.status} />
                                                            <button
                                                                onClick={(e) => {
                                                                    e.stopPropagation()
                                                                    setDeleteConfirm({
                                                                        message: 'Delete this comparison and all its audio samples?',
                                                                        onConfirm: () => deleteMutation.mutate(pc.id),
                                                                    })
                                                                }}
                                                                className="p-2 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                                                                title="Delete comparison"
                                                            >
                                                                <Trash2 className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        </>
                                    )}
                                </div>
                            )}

                            {/* ---- Analytics view ---- */}
                            {pastSubView === 'analytics' && (
                                <div className="bg-white rounded-xl shadow-lg p-6">
                                    <div className="flex items-center gap-2 mb-4">
                                        <BarChart3 className="w-5 h-5 text-gray-600" />
                                        <h2 className="text-lg font-semibold text-gray-900">Voice Analytics</h2>
                                        <p className="ml-2 text-xs text-gray-400">Aggregated metrics across all comparisons</p>
                                    </div>

                                    {analyticsLoading ? (
                                        <div className="flex items-center justify-center py-16 text-gray-500">
                                            <Loader2 className="w-6 h-6 animate-spin mr-2" />
                                            Loading analytics...
                                        </div>
                                    ) : sortedAnalytics.length === 0 ? (
                                        <div className="text-center py-16">
                                            <BarChart3 className="w-12 h-12 mx-auto text-gray-300 mb-3" />
                                            <p className="text-gray-600 font-medium">No analytics data yet</p>
                                            <p className="text-sm text-gray-500 mt-1">Run comparisons from the Playground tab to build up analytics.</p>
                                        </div>
                                    ) : (
                                        <div className="space-y-6">
                                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                                <div className="bg-gray-50 rounded-lg p-3 border border-gray-100">
                                                    <p className="text-[11px] text-gray-500 uppercase tracking-wide">Voices Tracked</p>
                                                    <p className="text-xl font-semibold text-gray-900">{analyticsOverview.totalVoices}</p>
                                                </div>
                                                <div className="bg-gray-50 rounded-lg p-3 border border-gray-100">
                                                    <p className="text-[11px] text-gray-500 uppercase tracking-wide">Samples Evaluated</p>
                                                    <p className="text-xl font-semibold text-gray-900">{analyticsOverview.totalSamples}</p>
                                                </div>
                                                <div className="bg-gray-50 rounded-lg p-3 border border-gray-100">
                                                    <p className="text-[11px] text-gray-500 uppercase tracking-wide">Overall Avg MOS</p>
                                                    <p className="text-xl font-semibold text-gray-900">{analyticsOverview.avgMos ?? '—'}</p>
                                                </div>
                                                <div className="bg-gray-50 rounded-lg p-3 border border-gray-100">
                                                    <p className="text-[11px] text-gray-500 uppercase tracking-wide">Overall Avg Latency</p>
                                                    <p className="text-xl font-semibold text-gray-900">{analyticsOverview.avgLatency != null ? `${analyticsOverview.avgLatency}ms` : '—'}</p>
                                                </div>
                                            </div>

                                            <div className="bg-white rounded-xl border border-gray-100 p-4">
                                                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
                                                    <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1 w-fit flex-wrap">
                                                        {BENCHMARK_METRIC_OPTIONS.map((metric) => (
                                                            <button
                                                                key={metric.key}
                                                                onClick={() => setSelectedBenchmarkMetric(metric.key)}
                                                                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                                                                    selectedBenchmarkMetric === metric.key
                                                                        ? 'bg-white text-gray-900 shadow-sm'
                                                                        : 'text-gray-500 hover:text-gray-700'
                                                                }`}
                                                            >
                                                                {metric.title}
                                                            </button>
                                                        ))}
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <label className="text-xs text-gray-500">Top results:</label>
                                                        <select
                                                            value={benchmarkTopN}
                                                            onChange={e => setBenchmarkTopN(Number(e.target.value))}
                                                            className="px-2 py-1.5 text-xs border border-gray-300 rounded-md bg-white"
                                                        >
                                                            {[5, 10, 15, 20].map(n => <option key={n} value={n}>{n}</option>)}
                                                        </select>
                                                    </div>
                                                </div>
                                                <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                                                    <div className="xl:col-span-2">
                                                        <BenchmarkMetricPanel
                                                            title={selectedBenchmarkConfig.title}
                                                            subtitle={selectedBenchmarkConfig.subtitle}
                                                            rows={benchmarkRows}
                                                            metricKey={selectedBenchmarkConfig.key}
                                                            higherIsBetter={selectedBenchmarkConfig.higherIsBetter}
                                                            maxValue={selectedBenchmarkConfig.maxValue}
                                                            unit={selectedBenchmarkConfig.unit}
                                                            topN={benchmarkTopN}
                                                        />
                                                    </div>
                                                    <BenchmarkTopList
                                                        rows={benchmarkRows}
                                                        metricKey={selectedBenchmarkConfig.key}
                                                        higherIsBetter={selectedBenchmarkConfig.higherIsBetter}
                                                        unit={selectedBenchmarkConfig.unit}
                                                        topN={benchmarkTopN}
                                                    />
                                                </div>
                                            </div>

                                            <div className="bg-white rounded-xl border border-gray-100 p-4">
                                                <h3 className="text-sm font-semibold text-gray-900 mb-3">Detailed Metrics Table</h3>
                                                <div className="overflow-x-auto">
                                                    <table className="w-full text-sm">
                                                        <thead>
                                                            <tr className="border-b border-gray-200">
                                                                {([
                                                                    ['provider', 'Provider'],
                                                                    ['model', 'Model'],
                                                                    ['voice_name', 'Voice'],
                                                                    ['sample_count', 'Samples'],
                                                                    ['avg_mos', 'Avg MOS'],
                                                                    ['avg_valence', 'Avg Valence'],
                                                                    ['avg_arousal', 'Avg Arousal'],
                                                                    ['avg_prosody', 'Avg Prosody'],
                                                                    ['avg_ttfb_ms', 'Avg TTFB'],
                                                                    ['avg_latency_ms', 'Total Latency'],
                                                                ] as [AnalyticsSortKey, string][]).map(([key, label]) => (
                                                                    <th
                                                                        key={key}
                                                                        onClick={() => toggleAnalyticsSort(key)}
                                                                        className="px-3 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider cursor-pointer hover:text-gray-700 select-none"
                                                                    >
                                                                        <span className="inline-flex items-center gap-1">
                                                                            {label}
                                                                            <ArrowUpDown className={`w-3 h-3 ${analyticsSortKey === key ? 'text-primary-600' : 'text-gray-300'}`} />
                                                                        </span>
                                                                    </th>
                                                                ))}
                                                            </tr>
                                                        </thead>
                                                        <tbody className="divide-y divide-gray-100">
                                                            {sortedAnalytics.map((row, idx) => (
                                                                <tr key={`${row.provider}-${row.model}-${row.voice_id}`} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
                                                                    <td className="px-3 py-3 whitespace-nowrap">
                                                                        <div className="flex items-center gap-2">
                                                                            <ProviderLogo provider={row.provider} size="sm" />
                                                                            <span className="font-medium text-gray-800">{getProviderInfo(row.provider).label}</span>
                                                                        </div>
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-gray-600 font-mono text-xs">{row.model}</td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-gray-700">{row.voice_name}</td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">{row.sample_count}</span>
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <AnalyticsMetricCell value={row.avg_mos} max={5} higherIsBetter />
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <AnalyticsMetricCell value={row.avg_valence} max={1} higherIsBetter />
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <AnalyticsMetricCell value={row.avg_arousal} max={1} higherIsBetter />
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <AnalyticsMetricCell value={row.avg_prosody} max={5} higherIsBetter />
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <AnalyticsMetricCell value={row.avg_ttfb_ms} unit="ms" higherIsBetter={false} />
                                                                    </td>
                                                                    <td className="px-3 py-3 whitespace-nowrap text-center">
                                                                        <AnalyticsMetricCell value={row.avg_latency_ms} unit="ms" higherIsBetter={false} />
                                                                    </td>
                                                                </tr>
                                                            ))}
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}

            {/* Delete confirmation modal */}
            {deleteConfirm && (
                <div className="fixed inset-0 z-50 flex items-center justify-center">
                    <div className="absolute inset-0 bg-black/40" onClick={() => setDeleteConfirm(null)} />
                    <div className="relative bg-white rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
                                <Trash2 className="w-5 h-5 text-red-600" />
                            </div>
                            <h3 className="text-lg font-semibold text-gray-900">Confirm Deletion</h3>
                        </div>
                        <p className="text-sm text-gray-600 mb-6">{deleteConfirm.message}</p>
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={() => setDeleteConfirm(null)}
                                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => {
                                    deleteConfirm.onConfirm()
                                    setDeleteConfirm(null)
                                }}
                                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
                            >
                                Delete
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}


// ============ HELPERS ============

function hasSecondProvider(comp: {
    provider_b?: string | null
    model_b?: string | null
    voices_b?: Array<{ id: string; name: string; sample_rate_hz?: number }> | null
}): boolean {
    const hasProviderMeta = Boolean(comp.provider_b && comp.model_b)
    if (!hasProviderMeta) return false
    if (!Object.prototype.hasOwnProperty.call(comp, 'voices_b')) return true
    if (comp.voices_b == null) return true
    return comp.voices_b.length > 0
}

function formatHz(hz: number): string {
    return hz >= 1000 ? `${(hz / 1000).toFixed(hz % 1000 === 0 ? 0 : 1)} kHz` : `${hz} Hz`
}

function buildVoiceHzMaps(comp: TTSComparison): { a: Record<string, number>; b: Record<string, number> } {
    const a: Record<string, number> = {}
    const b: Record<string, number> = {}
    for (const v of (comp.voices_a || [])) {
        if (v.sample_rate_hz) a[v.id] = v.sample_rate_hz
    }
    for (const v of (comp.voices_b || [])) {
        if (v.sample_rate_hz) b[v.id] = v.sample_rate_hz
    }
    return { a, b }
}

function HzBadge({ hz }: { hz?: number | null }) {
    if (!hz) return null
    return <span className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-full font-medium">{formatHz(hz)}</span>
}

// ============ PROVIDER PANEL SUB-COMPONENT ============

function ProviderPanel({
    label, color, providers, selectedProvider, selectedModel, selectedVoices,
    sampleRate, onProviderChange, onModelChange, onVoicesChange, onSampleRateChange,
}: {
    label: string
    color: 'blue' | 'purple'
    providers: TTSProvider[]
    selectedProvider: string
    selectedModel: string
    selectedVoices: TTSVoice[]
    sampleRate: number | null
    onProviderChange: (p: string) => void
    onModelChange: (m: string) => void
    onVoicesChange: (v: TTSVoice[]) => void
    onSampleRateChange: (hz: number | null) => void
}) {
    const [showAdvanced, setShowAdvanced] = useState(false)
    const providerData = providers.find(p => p.provider === selectedProvider)
    const models = providerData?.models || []
    const voices = providerData?.voices || []
    const supportedRates = providerData?.supported_sample_rates || []

    const bgGrad = color === 'blue' ? 'bg-gradient-to-br from-blue-50 to-sky-50' : 'bg-gradient-to-br from-purple-50 to-fuchsia-50'
    const borderColor = color === 'blue' ? 'border-blue-200' : 'border-purple-200'
    const badgeBg = color === 'blue' ? 'bg-blue-600' : 'bg-purple-600'
    const textColor = color === 'blue' ? 'text-blue-900' : 'text-purple-900'
    const chipBg = color === 'blue' ? 'bg-blue-100 text-blue-800 border-blue-200' : 'bg-purple-100 text-purple-800 border-purple-200'
    const ringColor = color === 'blue' ? 'focus:ring-blue-500' : 'focus:ring-purple-500'
    const advancedBorder = color === 'blue' ? 'border-blue-100' : 'border-purple-100'
    const advancedBg = color === 'blue' ? 'bg-blue-50/50' : 'bg-purple-50/50'

    return (
        <div className={`p-5 ${bgGrad} rounded-xl border-2 ${borderColor}`}>
            <div className="flex items-center gap-2 mb-4">
                <span className={`w-8 h-8 rounded-full ${badgeBg} text-white flex items-center justify-center text-sm font-bold`}>{label}</span>
                {selectedProvider ? <ProviderLogo provider={selectedProvider} size="md" /> : null}
                <span className={`font-semibold ${textColor}`}>
                    {selectedProvider ? getProviderInfo(selectedProvider).label : `Provider ${label}`}
                </span>
            </div>
            <div className="space-y-4">
                {/* Provider select */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">TTS Provider</label>
                    <select
                        value={selectedProvider}
                        onChange={e => onProviderChange(e.target.value)}
                        className={`w-full px-3 py-2.5 border border-gray-300 rounded-lg ${ringColor} focus:ring-2 bg-white`}
                    >
                        <option value="">Select provider...</option>
                        {providers.map(p => (
                            <option key={p.provider} value={p.provider}>
                                {getProviderInfo(p.provider).label}
                            </option>
                        ))}
                    </select>
                </div>

                {/* Model select */}
                {selectedProvider && (
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">TTS Model</label>
                        <select
                            value={selectedModel}
                            onChange={e => onModelChange(e.target.value)}
                            className={`w-full px-3 py-2.5 border border-gray-300 rounded-lg ${ringColor} focus:ring-2 bg-white`}
                        >
                            <option value="">Select model...</option>
                            {models.map(m => (
                                <option key={m} value={m}>{m}</option>
                            ))}
                        </select>
                    </div>
                )}

                {/* Voice multi-select */}
                {selectedProvider && (
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Voices</label>
                        <select
                            value=""
                            onChange={e => {
                                const vid = e.target.value
                                const voice = voices.find(v => v.id === vid)
                                if (voice && !selectedVoices.find(v => v.id === vid)) {
                                    onVoicesChange([...selectedVoices, voice])
                                }
                            }}
                            disabled={!selectedProvider}
                            className={`w-full px-3 py-2.5 border border-gray-300 rounded-lg ${ringColor} focus:ring-2 disabled:bg-gray-100 bg-white`}
                        >
                            <option value="">Add a voice...</option>
                            {voices.filter(v => !selectedVoices.find(sv => sv.id === v.id)).map(v => (
                                <option key={v.id} value={v.id}>
                                    {v.name} {v.is_custom ? '[Custom]' : ''} ({v.gender}, {v.accent})
                                </option>
                            ))}
                        </select>
                        <div className="flex flex-wrap gap-2 mt-2">
                            {selectedVoices.map(v => (
                                <div key={v.id} className={`flex items-center gap-1 ${chipBg} text-xs px-2 py-1 rounded-full border`}>
                                    <span>{v.name}</span>
                                    {v.is_custom && <span className="px-1 py-0.5 rounded bg-white/70 text-[10px] font-semibold">Custom</span>}
                                    <button onClick={() => onVoicesChange(selectedVoices.filter(sv => sv.id !== v.id))} className="rounded-full p-0.5 hover:opacity-70">
                                        <X className="w-3 h-3" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Advanced options (sample rate) */}
                {selectedProvider && supportedRates.length > 0 && (
                    <div className={`border ${advancedBorder} rounded-lg overflow-hidden`}>
                        <button
                            type="button"
                            onClick={() => setShowAdvanced(!showAdvanced)}
                            className={`w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-500 hover:text-gray-700 ${advancedBg} transition-colors`}
                        >
                            <span className="flex items-center gap-1.5">
                                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <circle cx="12" cy="12" r="3" /><path d="M12 1v6m0 6v6m8.66-15l-5.2 3m-6.92 4l-5.2 3M22.66 18l-5.2-3m-6.92-4l-5.2-3" />
                                </svg>
                                Advanced Options
                                {sampleRate && <span className="ml-1 text-[10px] px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded-full">{formatHz(sampleRate)}</span>}
                            </span>
                            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                        </button>
                        {showAdvanced && (
                            <div className={`px-3 py-3 ${advancedBg} border-t ${advancedBorder}`}>
                                <div>
                                    <label className="block text-xs font-medium text-gray-600 mb-1">
                                        Output Sample Rate
                                    </label>
                                    <select
                                        value={sampleRate ?? ''}
                                        onChange={e => onSampleRateChange(e.target.value ? Number(e.target.value) : null)}
                                        className={`w-full px-3 py-2 text-sm border border-gray-300 rounded-lg ${ringColor} focus:ring-2 bg-white`}
                                    >
                                        <option value="">Default (provider default)</option>
                                        {supportedRates.map(hz => (
                                            <option key={hz} value={hz}>{formatHz(hz)}</option>
                                        ))}
                                    </select>
                                    <p className="mt-1 text-[10px] text-gray-400">
                                        Frequency at which the TTS audio is generated. Higher rates yield better fidelity.
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}


// ============ SAMPLE GROUP SUB-COMPONENT ============

function SampleGroup({
    sampleIndex, text, samples, providerA, providerB, playingId, onPlay, numRuns, hzMapA, hzMapB,
}: {
    sampleIndex: number
    text: string
    samples: TTSSample[]
    providerA: string
    providerB?: string
    playingId: string | null
    onPlay: (id: string, url: string) => void
    numRuns: number
    hzMapA?: Record<string, number>
    hzMapB?: Record<string, number>
}) {
    const [expanded, setExpanded] = useState(false)
    const hasSideField = samples.some(s => s.side)
    const aSamples = samples.filter(s => hasSideField ? s.side === 'A' : s.provider === providerA)
    const bSamples = providerB ? samples.filter(s => hasSideField ? s.side === 'B' : s.provider === providerB) : []

    return (
        <div className="bg-gray-50 rounded-lg border border-gray-200 overflow-hidden">
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between p-4 hover:bg-gray-100 transition-colors"
            >
                <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-gray-700">Sample {sampleIndex + 1}</span>
                    <span className="text-xs text-gray-400 truncate max-w-md">{text}</span>
                </div>
                {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
            </button>

            {expanded && (
                <div className="border-t border-gray-200 p-4 space-y-3">
                    <p className="text-sm text-gray-700 italic mb-3">&ldquo;{text}&rdquo;</p>
                    <div className={`grid grid-cols-1 ${providerB ? 'md:grid-cols-2' : ''} gap-3`}>
                        {/* Provider A column */}
                        <div>
                            <p className="text-xs font-semibold text-blue-700 mb-2 flex items-center gap-1.5">
                                <span className="w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold">A</span>
                                <ProviderLogo provider={providerA} size="sm" />
                                {getProviderInfo(providerA).label}
                            </p>
                            {aSamples.map(s => (
                                <AudioCard key={s.id} sample={s} colorClass="blue" playingId={playingId} onPlay={onPlay} showRun={numRuns > 1} sampleRateHz={hzMapA?.[s.voice_id]} />
                            ))}
                        </div>
                        {providerB && (
                            <div>
                                <p className="text-xs font-semibold text-purple-700 mb-2 flex items-center gap-1.5">
                                    <span className="w-5 h-5 rounded-full bg-purple-600 text-white flex items-center justify-center text-[10px] font-bold">B</span>
                                    <ProviderLogo provider={providerB} size="sm" />
                                    {getProviderInfo(providerB).label}
                                </p>
                                {bSamples.map(s => (
                                    <AudioCard key={s.id} sample={s} colorClass="purple" playingId={playingId} onPlay={onPlay} showRun={numRuns > 1} sampleRateHz={hzMapB?.[s.voice_id]} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}


function AudioCard({ sample, colorClass, playingId, onPlay, showRun = false, sampleRateHz }: {
    sample: TTSSample; colorClass: 'blue' | 'purple'; playingId: string | null; onPlay: (id: string, url: string) => void; showRun?: boolean; sampleRateHz?: number
}) {
    const isPlaying = playingId === sample.id
    const borderC = colorClass === 'blue' ? 'border-blue-100' : 'border-purple-100'
    const bgC = colorClass === 'blue' ? 'bg-blue-50' : 'bg-purple-50'
    const textC = colorClass === 'blue' ? 'text-blue-600' : 'text-purple-600'

    return (
        <div className={`p-3 ${bgC} rounded-lg border ${borderC} mb-2`}>
            <div className="flex items-center gap-2">
                {sample.audio_url ? (
                    <button
                        onClick={() => onPlay(sample.id, sample.audio_url!)}
                        className={`w-8 h-8 rounded-full ${colorClass === 'blue' ? 'bg-blue-600 hover:bg-blue-700' : 'bg-purple-600 hover:bg-purple-700'} text-white flex items-center justify-center transition-colors flex-shrink-0`}
                    >
                        {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 ml-0.5" />}
                    </button>
                ) : (
                    <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0">
                        {sample.status === 'failed' ? <XCircle className="w-3.5 h-3.5 text-red-400" /> : <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />}
                    </div>
                )}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <p className={`text-sm font-medium ${textC}`}>{sample.voice_name || sample.voice_id}</p>
                        <HzBadge hz={sampleRateHz} />
                        {showRun && (
                            <span className="text-[10px] bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded">Run {(sample.run_index ?? 0) + 1}</span>
                        )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                        {sample.ttfb_ms != null && <span title="Time-to-first-byte">TTFB: {Math.round(sample.ttfb_ms)}ms</span>}
                        {sample.latency_ms != null && <span title="Total synthesis latency">Total: {Math.round(sample.latency_ms)}ms</span>}
                        {sample.duration_seconds != null && <span>Duration: {sample.duration_seconds.toFixed(1)}s</span>}
                    </div>
                </div>
            </div>
            {/* Metrics row */}
            {sample.evaluation_metrics && (
                <div className="flex flex-wrap gap-2 mt-2">
                    {sample.evaluation_metrics['MOS Score'] != null && (
                        <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">MOS: {sample.evaluation_metrics['MOS Score']}</span>
                    )}
                    {sample.evaluation_metrics['Prosody Score'] != null && (
                        <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">Prosody: {sample.evaluation_metrics['Prosody Score']}</span>
                    )}
                    {sample.evaluation_metrics['Valence'] != null && (
                        <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">Valence: {sample.evaluation_metrics['Valence']}</span>
                    )}
                    {sample.evaluation_metrics['Arousal'] != null && (
                        <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">Arousal: {sample.evaluation_metrics['Arousal']}</span>
                    )}
                </div>
            )}
        </div>
    )
}


// ============ ANALYTICS METRIC CELL ============

function providerBenchmarkColor(provider: string): string {
    const key = provider.toLowerCase()
    const palette: Record<string, string> = {
        openai: '#10b981',
        elevenlabs: '#8b5cf6',
        cartesia: '#3b82f6',
        deepgram: '#f59e0b',
        google: '#ef4444',
    }
    return palette[key] || '#6b7280'
}

function BenchmarkMetricPanel({
    title,
    subtitle,
    rows,
    metricKey,
    higherIsBetter,
    maxValue,
    unit,
    topN = 10,
}: {
    title: string
    subtitle: string
    rows: Array<{
        id: string
        provider: string
        model: string
        voice_name: string
        label: string
        short_label: string
        sample_count: number
        avg_mos: number | null
        avg_valence: number | null
        avg_arousal: number | null
        avg_prosody: number | null
        avg_ttfb_ms: number | null
        avg_latency_ms: number | null
    }>
    metricKey: BenchmarkMetricKey
    higherIsBetter: boolean
    maxValue?: number
    unit?: string
    topN?: number
}) {
    const sortedRows = [...rows]
        .filter(r => r[metricKey] != null)
        .sort((a, b) => {
            const aVal = (a[metricKey] as number)
            const bVal = (b[metricKey] as number)
            return higherIsBetter ? bVal - aVal : aVal - bVal
        })
        .slice(0, topN)

    const chartData = sortedRows.map((r) => {
        const rawValue = r[metricKey] as number
        return {
            id: r.id,
            provider: r.provider,
            label: r.label,
            shortLabel: r.short_label,
            model: r.model,
            voice: r.voice_name,
            sampleCount: r.sample_count,
            value: unit === 'ms' ? Number(rawValue.toFixed(0)) : Number(rawValue.toFixed(2)),
            valueLabel: unit === 'ms' ? `${Math.round(rawValue)}ms` : rawValue.toFixed(2),
        }
    })

    const chartWidth = Math.max(720, chartData.length * 72)

    return (
        <div className="bg-white rounded-xl border border-gray-100 p-4">
            <h3 className="text-sm font-semibold text-gray-900 tracking-wide">{title}</h3>
            <p className="text-xs text-gray-500 mb-3">{subtitle}</p>
            <div className="overflow-x-auto">
                <BarChart
                    width={chartWidth}
                    height={300}
                    data={chartData}
                    margin={{ top: 16, right: 8, left: 8, bottom: 70 }}
                >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis
                        dataKey="shortLabel"
                        interval={0}
                        angle={-40}
                        textAnchor="end"
                        height={70}
                        tick={{ fontSize: 10 }}
                    />
                    <YAxis domain={maxValue != null ? [0, maxValue] : [0, 'auto']} tick={{ fontSize: 10 }} />
                    <Tooltip
                        formatter={(value: any) => [unit === 'ms' ? `${value}ms` : value, title]}
                        labelFormatter={(_label, payload: any) => payload?.[0]?.payload?.label || _label}
                    />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        <LabelList dataKey="valueLabel" position="top" fontSize={10} />
                        {chartData.map((entry) => (
                            <Cell key={entry.id} fill={providerBenchmarkColor(entry.provider)} />
                        ))}
                    </Bar>
                </BarChart>
            </div>
        </div>
    )
}

function formatBenchmarkValue(value: number, unit?: string): string {
    if (unit === 'ms') return `${Math.round(value)}ms`
    return value.toFixed(2)
}

function BenchmarkTopList({
    rows,
    metricKey,
    higherIsBetter,
    unit,
    topN,
}: {
    rows: Array<{
        id: string
        provider: string
        model: string
        voice_name: string
        label: string
        short_label: string
        sample_count: number
        avg_mos: number | null
        avg_valence: number | null
        avg_arousal: number | null
        avg_prosody: number | null
        avg_ttfb_ms: number | null
        avg_latency_ms: number | null
    }>
    metricKey: BenchmarkMetricKey
    higherIsBetter: boolean
    unit?: string
    topN: number
}) {
    const topRows = [...rows]
        .filter(r => r[metricKey] != null)
        .sort((a, b) => {
            const aVal = a[metricKey] as number
            const bVal = b[metricKey] as number
            return higherIsBetter ? bVal - aVal : aVal - bVal
        })
        .slice(0, topN)

    return (
        <div className="bg-gray-50 rounded-xl border border-gray-100 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Ranking</h3>
            <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                {topRows.map((row, idx) => {
                    const value = row[metricKey] as number
                    return (
                        <div key={row.id} className="bg-white rounded-lg border border-gray-100 p-2.5 flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-gray-900 text-white text-[10px] font-bold flex items-center justify-center">
                                {idx + 1}
                            </span>
                            <ProviderLogo provider={row.provider} size="sm" />
                            <div className="min-w-0 flex-1">
                                <p className="text-xs font-medium text-gray-800 truncate">{row.voice_name}</p>
                                <p className="text-[10px] text-gray-500 truncate">{getProviderInfo(row.provider).label} • {row.model}</p>
                            </div>
                            <span className="text-xs font-semibold text-gray-800 bg-gray-100 px-2 py-1 rounded-md">
                                {formatBenchmarkValue(value, unit)}
                            </span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function AnalyticsMetricCell({ value, max, unit, higherIsBetter = true }: {
    value: number | null; max?: number; unit?: string; higherIsBetter?: boolean
}) {
    if (value == null) return <span className="text-gray-300">—</span>

    let colorClass = 'text-gray-700'
    if (max != null) {
        const ratio = value / max
        if (higherIsBetter) {
            if (ratio >= 0.75) colorClass = 'text-green-600 font-semibold'
            else if (ratio >= 0.5) colorClass = 'text-yellow-600'
            else colorClass = 'text-red-500'
        } else {
            if (ratio <= 0.25) colorClass = 'text-green-600 font-semibold'
            else if (ratio <= 0.5) colorClass = 'text-yellow-600'
            else colorClass = 'text-red-500'
        }
    } else if (!higherIsBetter) {
        if (value <= 300) colorClass = 'text-green-600 font-semibold'
        else if (value <= 600) colorClass = 'text-yellow-600'
        else colorClass = 'text-red-500'
    }

    const display = unit === 'ms' ? `${Math.round(value)}ms` : value.toFixed(2)
    return <span className={colorClass}>{display}</span>
}
