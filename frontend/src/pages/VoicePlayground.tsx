import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
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
    Headphones,
} from 'lucide-react'

// ============ TYPES ============

interface TTSVoice {
    id: string
    name: string
    gender: string
    accent: string
}

interface TTSProvider {
    provider: string
    models: string[]
    voices: TTSVoice[]
}

interface TTSSample {
    id: string
    provider: string
    model: string
    voice_id: string
    voice_name: string
    sample_index: number
    text: string
    audio_url: string | null
    audio_s3_key: string | null
    duration_seconds: number | null
    latency_ms: number | null
    evaluation_metrics: Record<string, number | string | null> | null
    status: string
    error_message: string | null
}

interface TTSComparison {
    id: string
    name: string
    status: string
    provider_a: string
    model_a: string
    voices_a: Array<{ id: string; name: string }>
    provider_b: string
    model_b: string
    voices_b: Array<{ id: string; name: string }>
    sample_texts: string[]
    blind_test_results: Array<{ sample_index: number; preferred: string }> | null
    evaluation_summary: Record<string, any> | null
    error_message: string | null
    samples: TTSSample[]
    created_at: string
    updated_at: string
}

// ============ CONSTANTS ============

const DEFAULT_SAMPLE_TEXTS = [
    "Hello! Thank you for calling customer support. How may I assist you today?",
    "Your order number is 1-2-3-4-5-6-7-8-9. It will be delivered on January 15th, 2025.",
    "I understand your concern. Let me look into this for you right away.",
    "The total amount due is $1,234.56. Would you like to proceed with the payment?",
    "Is there anything else I can help you with today? We appreciate your business!",
]

const PROVIDER_DISPLAY: Record<string, string> = {
    openai: 'OpenAI',
    elevenlabs: 'ElevenLabs',
    cartesia: 'Cartesia',
    deepgram: 'Deepgram',
    google: 'Google',
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
    const aWins = aVal !== null && bVal !== null && (higherIsBetter ? aVal > bVal : aVal < bVal)
    const bWins = aVal !== null && bVal !== null && (higherIsBetter ? bVal > aVal : bVal < aVal)

    return (
        <div className="bg-white rounded-lg p-4 border border-gray-100 shadow-sm">
            <p className="text-xs text-gray-500 mb-2 font-medium">{label}</p>
            <div className="flex items-baseline gap-3">
                <span className={`text-lg font-bold ${aWins ? 'text-blue-600' : 'text-gray-700'}`}>
                    {aVal !== null ? `${aVal}${unit || ''}` : '—'}
                </span>
                <span className="text-xs text-gray-400">vs</span>
                <span className={`text-lg font-bold ${bWins ? 'text-purple-600' : 'text-gray-700'}`}>
                    {bVal !== null ? `${bVal}${unit || ''}` : '—'}
                </span>
            </div>
        </div>
    )
}

// ============ MAIN COMPONENT ============

export default function VoicePlayground() {
    const { playingId, play, stop } = useAudioPlayer()

    // --- Provider data ---
    const { data: providers = [], isLoading: providersLoading } = useQuery<TTSProvider[]>({
        queryKey: ['tts-providers'],
        queryFn: () => apiClient.listTTSProviders(),
    })

    // --- Configuration state ---
    const [providerA, setProviderA] = useState('')
    const [modelA, setModelA] = useState('')
    const [selectedVoicesA, setSelectedVoicesA] = useState<TTSVoice[]>([])

    const [providerB, setProviderB] = useState('')
    const [modelB, setModelB] = useState('')
    const [selectedVoicesB, setSelectedVoicesB] = useState<TTSVoice[]>([])

    const [sampleTexts, setSampleTexts] = useState<string[]>(DEFAULT_SAMPLE_TEXTS.slice(0, 3))
    const [customText, setCustomText] = useState('')
    const [selectedTranscript, setSelectedTranscript] = useState(0)

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

    // Transition from progress to blind-test or results when generation/evaluation completes
    useEffect(() => {
        if (!comparison) return
        if (step === 'progress') {
            if (comparison.status === 'completed') {
                buildBlindPairs(comparison)
                setStep('blind-test')
            } else if (comparison.status === 'failed') {
                // stay on progress to show error
            }
        }
    }, [comparison, step])

    // voice/model lists are consumed by ProviderPanel sub-components via the providers array

    // --- Mutations ---
    const createMutation = useMutation({
        mutationFn: async () => {
            const comp = await apiClient.createTTSComparison({
                provider_a: providerA,
                model_a: modelA,
                voices_a: selectedVoicesA.map(v => ({ id: v.id, name: v.name })),
                provider_b: providerB,
                model_b: modelB,
                voices_b: selectedVoicesB.map(v => ({ id: v.id, name: v.name })),
                sample_texts: sampleTexts,
            })
            await apiClient.generateTTSComparison(comp.id)
            return comp
        },
        onSuccess: (comp) => {
            setActiveComparisonId(comp.id)
            setStep('progress')
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
            const aSamples = samplesForIdx.filter(s => s.provider === comp.provider_a)
            const bSamples = samplesForIdx.filter(s => s.provider === comp.provider_b)
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
    }

    const canRun = providerA && providerB && providerA !== providerB &&
        modelA && modelB && selectedVoicesA.length > 0 && selectedVoicesB.length > 0 &&
        sampleTexts.length > 0

    function resetPlayground() {
        stop()
        setProviderA('')
        setProviderB('')
        setModelA('')
        setModelB('')
        setSelectedVoicesA([])
        setSelectedVoicesB([])
        setSampleTexts(DEFAULT_SAMPLE_TEXTS.slice(0, 3))
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
                {step !== 'configure' && (
                    <Button variant="ghost" onClick={resetPlayground} leftIcon={<RotateCcw className="w-4 h-4" />}>
                        New Comparison
                    </Button>
                )}
            </div>

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
                        {/* Custom text */}
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
                        </div>
                        {/* Active text chips */}
                        <div className="flex flex-wrap gap-2 mt-3">
                            {sampleTexts.map((t, idx) => (
                                <div key={idx} className="flex items-center gap-1 bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full border border-indigo-200 max-w-xs">
                                    <span className="truncate">{t.slice(0, 50)}{t.length > 50 ? '...' : ''}</span>
                                    <button onClick={() => setSampleTexts(sampleTexts.filter((_, i) => i !== idx))} className="hover:text-indigo-600 rounded-full p-0.5">
                                        <X className="w-3 h-3" />
                                    </button>
                                </div>
                            ))}
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
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6 relative">
                                    {/* Provider A */}
                                    <ProviderPanel
                                        label="A"
                                        color="blue"
                                        providers={providers}
                                        otherProvider={providerB}
                                        selectedProvider={providerA}
                                        selectedModel={modelA}
                                        selectedVoices={selectedVoicesA}
                                        onProviderChange={p => { setProviderA(p); setModelA(''); setSelectedVoicesA([]) }}
                                        onModelChange={setModelA}
                                        onVoicesChange={setSelectedVoicesA}
                                    />

                                    {/* VS Badge */}
                                    <div className="hidden lg:flex absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10">
                                        <span className="px-4 py-2 bg-gray-900 text-white rounded-full text-sm font-bold shadow-xl">VS</span>
                                    </div>

                                    {/* Provider B */}
                                    <ProviderPanel
                                        label="B"
                                        color="purple"
                                        providers={providers}
                                        otherProvider={providerA}
                                        selectedProvider={providerB}
                                        selectedModel={modelB}
                                        selectedVoices={selectedVoicesB}
                                        onProviderChange={p => { setProviderB(p); setModelB(''); setSelectedVoicesB([]) }}
                                        onModelChange={setModelB}
                                        onVoicesChange={setSelectedVoicesB}
                                    />
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
                                        {createMutation.isPending ? 'Starting...' : 'Run Comparison'}
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
                            <h2 className="text-lg font-semibold text-gray-900">{comparison.name}</h2>
                            <p className="text-sm text-gray-500 mt-1">
                                {PROVIDER_DISPLAY[comparison.provider_a] || comparison.provider_a} vs {PROVIDER_DISPLAY[comparison.provider_b] || comparison.provider_b}
                            </p>
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
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                        {comparison.samples.map(s => (
                            <div key={s.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg text-xs">
                                {s.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />}
                                {s.status === 'generating' && <Loader2 className="w-3.5 h-3.5 text-yellow-500 animate-spin flex-shrink-0" />}
                                {s.status === 'pending' && <Clock className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />}
                                {s.status === 'failed' && <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />}
                                <span className="truncate text-gray-700">{s.voice_name || s.voice_id}</span>
                                {s.latency_ms && <span className="text-gray-400 ml-auto">{Math.round(s.latency_ms)}ms</span>}
                            </div>
                        ))}
                    </div>

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
                                <h2 className="text-lg font-semibold text-gray-900">{comparison.name}</h2>
                                <p className="text-sm text-gray-500">
                                    {comparison.sample_texts?.length || 0} samples &middot; {comparison.samples?.length || 0} audio files
                                </p>
                            </div>
                            <StatusBadge status={comparison.status} />
                        </div>

                        {/* Winner Banner */}
                        {comparison.evaluation_summary && (() => {
                            const sumA = comparison.evaluation_summary.provider_a || {}
                            const sumB = comparison.evaluation_summary.provider_b || {}
                            const mosA = sumA['MOS Score'] ?? 0
                            const mosB = sumB['MOS Score'] ?? 0
                            const bt = comparison.evaluation_summary.blind_test
                            const btScore = bt ? (bt.a_wins - bt.b_wins) : 0
                            const winner = (mosA + btScore * 0.1) >= (mosB) ? 'A' : 'B'
                            const winnerName = winner === 'A'
                                ? (PROVIDER_DISPLAY[comparison.provider_a] || comparison.provider_a)
                                : (PROVIDER_DISPLAY[comparison.provider_b] || comparison.provider_b)

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
                            return (
                                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
                                    <MetricCard label="MOS Score" valueA={sumA['MOS Score']} valueB={sumB['MOS Score']} higherIsBetter />
                                    <MetricCard label="Valence" valueA={sumA['Valence']} valueB={sumB['Valence']} higherIsBetter />
                                    <MetricCard label="Arousal" valueA={sumA['Arousal']} valueB={sumB['Arousal']} higherIsBetter />
                                    <MetricCard label="Prosody" valueA={sumA['Prosody Score']} valueB={sumB['Prosody Score']} higherIsBetter />
                                    <MetricCard label="Avg Latency" valueA={sumA['avg_latency_ms']} valueB={sumB['avg_latency_ms']} unit="ms" higherIsBetter={false} />
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
                                        <div className="text-center">
                                            <p className="text-xs text-gray-500">{PROVIDER_DISPLAY[comparison.provider_a] || comparison.provider_a}</p>
                                            <p className="text-2xl font-bold text-blue-600">{bt.a_pct}%</p>
                                            <p className="text-xs text-gray-400">{bt.a_wins} wins</p>
                                        </div>
                                        <span className="text-gray-300 text-xl">vs</span>
                                        <div className="text-center">
                                            <p className="text-xs text-gray-500">{PROVIDER_DISPLAY[comparison.provider_b] || comparison.provider_b}</p>
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
                                <span className="text-sm font-medium text-gray-700">
                                    {PROVIDER_DISPLAY[comparison.provider_a] || comparison.provider_a} ({comparison.model_a})
                                </span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center text-xs font-bold">B</span>
                                <span className="text-sm font-medium text-gray-700">
                                    {PROVIDER_DISPLAY[comparison.provider_b] || comparison.provider_b} ({comparison.model_b})
                                </span>
                            </div>
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
                                    samples={comparison.samples.filter(s => s.sample_index === idx)}
                                    providerA={comparison.provider_a}
                                    providerB={comparison.provider_b}
                                    playingId={playingId}
                                    onPlay={play}
                                />
                            ))}
                        </div>
                    </div>

                    {/* Actions */}
                    <div className="flex justify-center">
                        <Button variant="primary" leftIcon={<RotateCcw className="w-4 h-4" />} onClick={resetPlayground}>
                            Run New Comparison
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}


// ============ PROVIDER PANEL SUB-COMPONENT ============

function ProviderPanel({
    label, color, providers, otherProvider, selectedProvider, selectedModel, selectedVoices,
    onProviderChange, onModelChange, onVoicesChange,
}: {
    label: string
    color: 'blue' | 'purple'
    providers: TTSProvider[]
    otherProvider: string
    selectedProvider: string
    selectedModel: string
    selectedVoices: TTSVoice[]
    onProviderChange: (p: string) => void
    onModelChange: (m: string) => void
    onVoicesChange: (v: TTSVoice[]) => void
}) {
    const providerData = providers.find(p => p.provider === selectedProvider)
    const models = providerData?.models || []
    const voices = providerData?.voices || []

    const bgGrad = color === 'blue' ? 'bg-gradient-to-br from-blue-50 to-sky-50' : 'bg-gradient-to-br from-purple-50 to-fuchsia-50'
    const borderColor = color === 'blue' ? 'border-blue-200' : 'border-purple-200'
    const badgeBg = color === 'blue' ? 'bg-blue-600' : 'bg-purple-600'
    const textColor = color === 'blue' ? 'text-blue-900' : 'text-purple-900'
    const chipBg = color === 'blue' ? 'bg-blue-100 text-blue-800 border-blue-200' : 'bg-purple-100 text-purple-800 border-purple-200'
    const ringColor = color === 'blue' ? 'focus:ring-blue-500' : 'focus:ring-purple-500'

    return (
        <div className={`p-5 ${bgGrad} rounded-xl border-2 ${borderColor}`}>
            <div className="flex items-center gap-2 mb-4">
                <span className={`w-8 h-8 rounded-full ${badgeBg} text-white flex items-center justify-center text-sm font-bold`}>{label}</span>
                <span className={`font-semibold ${textColor}`}>Provider {label}</span>
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
                        {providers.filter(p => p.provider !== otherProvider).map(p => (
                            <option key={p.provider} value={p.provider}>
                                {PROVIDER_DISPLAY[p.provider] || p.provider}
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
                                <option key={v.id} value={v.id}>{v.name} ({v.gender}, {v.accent})</option>
                            ))}
                        </select>
                        <div className="flex flex-wrap gap-2 mt-2">
                            {selectedVoices.map(v => (
                                <div key={v.id} className={`flex items-center gap-1 ${chipBg} text-xs px-2 py-1 rounded-full border`}>
                                    <span>{v.name}</span>
                                    <button onClick={() => onVoicesChange(selectedVoices.filter(sv => sv.id !== v.id))} className="rounded-full p-0.5 hover:opacity-70">
                                        <X className="w-3 h-3" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}


// ============ SAMPLE GROUP SUB-COMPONENT ============

function SampleGroup({
    sampleIndex, text, samples, providerA, providerB, playingId, onPlay,
}: {
    sampleIndex: number
    text: string
    samples: TTSSample[]
    providerA: string
    providerB: string
    playingId: string | null
    onPlay: (id: string, url: string) => void
}) {
    const [expanded, setExpanded] = useState(false)
    const aSamples = samples.filter(s => s.provider === providerA)
    const bSamples = samples.filter(s => s.provider === providerB)

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
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {/* Provider A column */}
                        <div>
                            <p className="text-xs font-semibold text-blue-700 mb-2 flex items-center gap-1">
                                <span className="w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold">A</span>
                                {PROVIDER_DISPLAY[providerA] || providerA}
                            </p>
                            {aSamples.map(s => (
                                <AudioCard key={s.id} sample={s} colorClass="blue" playingId={playingId} onPlay={onPlay} />
                            ))}
                        </div>
                        {/* Provider B column */}
                        <div>
                            <p className="text-xs font-semibold text-purple-700 mb-2 flex items-center gap-1">
                                <span className="w-5 h-5 rounded-full bg-purple-600 text-white flex items-center justify-center text-[10px] font-bold">B</span>
                                {PROVIDER_DISPLAY[providerB] || providerB}
                            </p>
                            {bSamples.map(s => (
                                <AudioCard key={s.id} sample={s} colorClass="purple" playingId={playingId} onPlay={onPlay} />
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}


function AudioCard({ sample, colorClass, playingId, onPlay }: {
    sample: TTSSample; colorClass: 'blue' | 'purple'; playingId: string | null; onPlay: (id: string, url: string) => void
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
                    <p className={`text-sm font-medium ${textC}`}>{sample.voice_name || sample.voice_id}</p>
                    <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                        {sample.latency_ms != null && <span>Latency: {Math.round(sample.latency_ms)}ms</span>}
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
