import { useState, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
import {
    Play,
    Pause,
    Volume2,
    Trophy,
    BarChart3,
    DollarSign,
    Clock,
    Mic,
    Share2,
    RotateCcw,
    Plus,
    X,
    Loader2,
    FileText
} from 'lucide-react'

// ============ MOCK DATA ============

const TTS_PROVIDERS = [
    { id: 'murf-falcon', name: 'Murf Falcon (2024)', costPer1M: 1.60, costPer100kMin: 1200 },
    { id: 'elevenlabs-turbo', name: 'ElevenLabs Turbo v2.5', costPer1M: 4.20, costPer100kMin: 3100 },
    { id: 'cartesia-sonic', name: 'Cartesia Sonic', costPer1M: 2.40, costPer100kMin: 1800 },
    { id: 'azure-neural', name: 'Azure Neural TTS', costPer1M: 1.00, costPer100kMin: 750 },
    { id: 'google-wavenet', name: 'Google WaveNet', costPer1M: 1.60, costPer100kMin: 1200 },
    { id: 'amazon-polly', name: 'Amazon Polly Neural', costPer1M: 0.80, costPer100kMin: 600 },
]

const SAMPLE_TRANSCRIPTS = [
    "Hello! Thank you for calling customer support. How may I assist you today?",
    "Your order number is 1-2-3-4-5-6-7-8-9. It will be delivered on January 15th, 2025.",
    "I understand your concern. Let me look into this for you right away.",
    "The total amount due is $1,234.56. Would you like to proceed with the payment?",
    "Is there anything else I can help you with today? We appreciate your business!"
]

const PROVIDER_VOICES: Record<string, { id: string; name: string; gender: string; accent: string; language: string }[]> = {
    'murf-falcon': [
        { id: 'murf-aisha', name: 'Aisha', gender: 'Female', accent: 'Indian', language: 'English' },
        { id: 'murf-james', name: 'James', gender: 'Male', accent: 'American', language: 'English' },
        { id: 'murf-sofia', name: 'Sofia', gender: 'Female', accent: 'British', language: 'English' },
    ],
    'elevenlabs-turbo': [
        { id: 'el-rachel', name: 'Rachel', gender: 'Female', accent: 'American', language: 'English' },
        { id: 'el-adam', name: 'Adam', gender: 'Male', accent: 'American', language: 'English' },
        { id: 'el-bella', name: 'Bella', gender: 'Female', accent: 'American', language: 'English' },
    ],
    'cartesia-sonic': [
        { id: 'cs-nova', name: 'Nova', gender: 'Female', accent: 'American', language: 'English' },
        { id: 'cs-echo', name: 'Echo', gender: 'Male', accent: 'British', language: 'English' },
    ],
    'azure-neural': [
        { id: 'az-jenny', name: 'Jenny', gender: 'Female', accent: 'American', language: 'English' },
        { id: 'az-guy', name: 'Guy', gender: 'Male', accent: 'American', language: 'English' },
    ],
    'google-wavenet': [
        { id: 'gw-wavenet-a', name: 'WaveNet A', gender: 'Female', accent: 'American', language: 'English' },
        { id: 'gw-wavenet-b', name: 'WaveNet B', gender: 'Male', accent: 'American', language: 'English' },
    ],
    'amazon-polly': [
        { id: 'ap-joanna', name: 'Joanna', gender: 'Female', accent: 'American', language: 'English' },
        { id: 'ap-matthew', name: 'Matthew', gender: 'Male', accent: 'American', language: 'English' },
    ],
}

const AGENT_PLATFORMS = [
    { id: 'vapi', name: 'Vapi' },
    { id: 'retell', name: 'Retell' },
    { id: 'bland', name: 'Bland AI' },
    { id: 'vocode', name: 'Vocode' },
]

const MOCK_CALL_TRANSCRIPTS = [
    {
        agentLine: "Hello! Thank you for calling customer support. My name is Sarah, how may I assist you today?",
        customerLine: "Hi Sarah, I'm calling about my recent order. I haven't received it yet.",
    },
    {
        agentLine: "I'd be happy to help you with that. Could you please provide me with your order number?",
        customerLine: "Yes, it's 1-2-3-4-5-6-7-8-9.",
    },
    {
        agentLine: "Thank you. I can see your order was shipped on January 10th. It's scheduled to arrive by January 15th, 2025.",
        customerLine: "Okay, that's reassuring. Can you confirm the delivery address?",
    },
    {
        agentLine: "Of course! The delivery address is 123 Main Street, Apartment 4B, New York, NY 10001.",
        customerLine: "That's correct. Thank you for checking.",
    },
]

// Generate mock results with per-call metrics
const generateMockResults = (providerA: string, providerB: string, voicesA: string[], voicesB: string[], numCalls: number, mode: 'agent' | 'tts' = 'agent', ttsText: string = '') => {
    const provA = TTS_PROVIDERS.find(p => p.id === providerA)
    const provB = TTS_PROVIDERS.find(p => p.id === providerB)

    const callRecordings = Array.from({ length: numCalls }, (_, i) => ({
        id: `call-${i + 1}`,
        callNumber: i + 1,
        duration: Math.floor(Math.random() * 120 + 30),
        transcripts: mode === 'tts'
            ? [{ agentLine: ttsText, customerLine: null }]
            : MOCK_CALL_TRANSCRIPTS.slice(0, Math.floor(Math.random() * 3 + 2)),
        voiceSamples: {
            A: voicesA.map(vId => {
                const v = PROVIDER_VOICES[providerA]?.find(p => p.id === vId)
                return { id: vId, name: v?.name || vId }
            }),
            B: voicesB.map(vId => {
                const v = PROVIDER_VOICES[providerB]?.find(p => p.id === vId)
                return { id: vId, name: v?.name || vId }
            })
        },
        metrics: {
            ttfb: { A: Math.floor(Math.random() * 200 + 300), B: Math.floor(Math.random() * 300 + 400) },
            gibberishRate: { A: (Math.random() * 8).toFixed(1), B: (Math.random() * 12).toFixed(1) },
            pronunciationAccuracy: { A: (Math.random() * 8 + 92).toFixed(1), B: (Math.random() * 12 + 85).toFixed(1) },
            emotionalMatch: { A: Math.floor(Math.random() * 15 + 80), B: Math.floor(Math.random() * 20 + 70) },
            mos: { A: (Math.random() * 0.8 + 4.0).toFixed(2), B: (Math.random() * 0.8 + 3.8).toFixed(2) },
        }
    }))

    return {
        providerA: provA?.name || providerA,
        providerB: provB?.name || providerB,
        winner: Math.random() > 0.5 ? 'A' : 'B',
        winnerPreference: Math.floor(Math.random() * 30 + 55),
        callRecordings,
        metrics: {
            blindPreference: { A: Math.floor(Math.random() * 30 + 50), B: Math.floor(Math.random() * 30 + 30) },
            gibberishRate: { A: (Math.random() * 5 + 0.5).toFixed(1), B: (Math.random() * 8 + 1).toFixed(1) },
            pronunciationAccuracy: { A: (Math.random() * 5 + 94).toFixed(1), B: (Math.random() * 8 + 88).toFixed(1) },
            emotionalMatch: { A: Math.floor(Math.random() * 10 + 85), B: Math.floor(Math.random() * 15 + 75) },
            mos: { A: (Math.random() * 0.5 + 4.3).toFixed(2), B: (Math.random() * 0.5 + 4.1).toFixed(2) },
            avgTTFB: { A: Math.floor(Math.random() * 200 + 350), B: Math.floor(Math.random() * 300 + 500) },
            costPer1M: { A: provA?.costPer1M || 1.60, B: provB?.costPer1M || 4.20 },
            costPer100kMin: { A: provA?.costPer100kMin || 1200, B: provB?.costPer100kMin || 3100 },
        }
    }
}

interface CustomVoice {
    id: string
    name: string
    gender: string
    accent: string
    language: string
}

function VoicePreview({ voice, isPlaying, onPlay, colorScheme = 'blue' }: {
    voice: CustomVoice
    isPlaying: boolean
    onPlay: () => void
    colorScheme?: 'blue' | 'purple'
}) {
    const bgColor = colorScheme === 'blue' ? 'bg-blue-100' : 'bg-purple-100'
    const textColor = colorScheme === 'blue' ? 'text-blue-700' : 'text-purple-700'
    const buttonColor = colorScheme === 'blue' ? 'bg-blue-600 hover:bg-blue-700' : 'bg-purple-600 hover:bg-purple-700'

    return (
        <div className={`mt-3 p-3 ${bgColor} rounded-lg`}>
            <div className="flex items-start gap-3">
                <button
                    onClick={onPlay}
                    className={`flex-shrink-0 w-10 h-10 rounded-full ${buttonColor} text-white flex items-center justify-center transition-colors shadow-md`}
                >
                    {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
                </button>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <span className={`text-sm font-medium ${textColor}`}>{voice.name}</span>
                        <span className="text-xs text-gray-500">• {voice.gender} • {voice.accent}</span>
                    </div>
                    <p className="text-xs text-gray-600 italic line-clamp-2">"{SAMPLE_TRANSCRIPTS[0]}"</p>
                </div>
            </div>
        </div>
    )
}

export default function VoicePlayground() {
    const [providerA, setProviderA] = useState('')
    const [providerB, setProviderB] = useState('')
    const [selectedVoicesA, setSelectedVoicesA] = useState<string[]>([])
    const [selectedVoicesB, setSelectedVoicesB] = useState<string[]>([])

    const [selectedScenario, setSelectedScenario] = useState('')
    const [customScenario, setCustomScenario] = useState('')
    const [useCustomScenario, setUseCustomScenario] = useState(false)
    const [selectedAgent, setSelectedAgent] = useState('')
    const [numberOfCalls, setNumberOfCalls] = useState(5)

    const [playingVoice, setPlayingVoice] = useState<string | null>(null)
    const audioRef = useRef<HTMLAudioElement | null>(null)

    const [isRunning, setIsRunning] = useState(false)
    const [results, setResults] = useState<ReturnType<typeof generateMockResults> | null>(null)

    const [selectedTranscript, setSelectedTranscript] = useState(0)

    // Evaluation mode state
    const [evaluationMode, setEvaluationMode] = useState<'agent' | 'tts'>('agent')
    const [ttsText, setTtsText] = useState(SAMPLE_TRANSCRIPTS[0])

    // Cost calculator state
    const [costMinutes, setCostMinutes] = useState(100000)
    const [costCharacters, setCostCharacters] = useState(1000000)

    const { data: scenarios = [] } = useQuery({
        queryKey: ['scenarios'],
        queryFn: () => apiClient.listScenarios(),
    })

    const voicesA = useMemo(() => providerA ? (PROVIDER_VOICES[providerA] || []) : [], [providerA])
    const voicesB = useMemo(() => providerB ? (PROVIDER_VOICES[providerB] || []) : [], [providerB])

    const activeVoicesA = useMemo(() => voicesA.filter(v => selectedVoicesA.includes(v.id)), [voicesA, selectedVoicesA])
    const activeVoicesB = useMemo(() => voicesB.filter(v => selectedVoicesB.includes(v.id)), [voicesB, selectedVoicesB])

    const canRunTest = () => {
        const basicCheck = providerA && providerB && providerA !== providerB && selectedVoicesA.length > 0 && selectedVoicesB.length > 0 && numberOfCalls >= 1
        if (evaluationMode === 'agent') {
            return basicCheck && (useCustomScenario ? customScenario.trim() : selectedScenario) && selectedAgent
        }
        return basicCheck && ttsText.trim()
    }

    const handlePlayVoice = (voiceId: string) => {
        if (playingVoice === voiceId) {
            setPlayingVoice(null)
        } else {
            setPlayingVoice(voiceId)
            setTimeout(() => setPlayingVoice(null), 3000)
        }
    }

    const handleRunTest = () => {
        if (!canRunTest()) return
        setIsRunning(true)
        setResults(null)
        setTimeout(() => {
            setResults(generateMockResults(providerA, providerB, selectedVoicesA, selectedVoicesB, numberOfCalls, evaluationMode, ttsText))
            setIsRunning(false)
        }, 2000)
    }

    const resetPlayground = () => {
        setProviderA('')
        setProviderB('')
        setSelectedVoicesA([])
        setSelectedVoicesB([])
        setSelectedScenario('')
        setCustomScenario('')
        setSelectedAgent('')
        setNumberOfCalls(5)
        setResults(null)
        setPlayingVoice(null)
        setEvaluationMode('agent')
        setTtsText(SAMPLE_TRANSCRIPTS[0])
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
                        <Mic className="w-8 h-8 text-primary-600" />
                        Voice Playground
                    </h1>
                    <p className="mt-2 text-sm text-gray-600">A/B test TTS providers — Compare voice quality, latency, and cost</p>
                </div>
                {(providerA || providerB || results) && (
                    <Button variant="ghost" onClick={resetPlayground} leftIcon={<RotateCcw className="w-4 h-4" />}>Reset</Button>
                )}
            </div>

            {/* Mode Switcher */}
            <div className="flex justify-center bg-white p-2 rounded-xl shadow-sm border border-gray-100 mb-6 w-fit mx-auto">
                <div className="flex bg-gray-100 p-1 rounded-lg">
                    <button
                        onClick={() => setEvaluationMode('agent')}
                        className={`px-6 py-2 rounded-md text-sm font-medium transition-all duration-200 flex items-center gap-2 ${evaluationMode === 'agent' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                    >
                        <Mic className="w-4 h-4" />
                        Voice Agent
                    </button>
                    <button
                        onClick={() => { setEvaluationMode('tts'); setTtsText(SAMPLE_TRANSCRIPTS[selectedTranscript]) }}
                        className={`px-6 py-2 rounded-md text-sm font-medium transition-all duration-200 flex items-center gap-2 ${evaluationMode === 'tts' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                    >
                        <Volume2 className="w-4 h-4" />
                        TTS Only
                    </button>
                </div>
            </div>

            {/* Sample Transcripts */}
            <div className="bg-gradient-to-r from-indigo-50 to-violet-50 rounded-xl p-4 border border-indigo-100">
                <div className="flex items-center gap-2 mb-3">
                    <FileText className="w-5 h-5 text-indigo-600" />
                    <h3 className="font-semibold text-indigo-900">Sample Transcript</h3>
                </div>
                <div className="flex gap-2 flex-wrap">
                    {SAMPLE_TRANSCRIPTS.map((_, idx) => (
                        <button
                            key={idx}
                            onClick={() => {
                                setSelectedTranscript(idx)
                                if (evaluationMode === 'tts') setTtsText(SAMPLE_TRANSCRIPTS[idx])
                            }}
                            className={`px-3 py-2 text-xs rounded-lg transition-all ${selectedTranscript === idx ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-indigo-100 border border-indigo-200'}`}
                        >
                            Sample {idx + 1}
                        </button>
                    ))}
                </div>
                <p className="mt-3 p-3 bg-white rounded-lg text-sm text-gray-700 italic border border-indigo-100">"{SAMPLE_TRANSCRIPTS[selectedTranscript]}"</p>
            </div>

            {/* TTS Input */}
            {evaluationMode === 'tts' && (
                <div className="bg-white rounded-xl shadow-sm p-6 border border-indigo-100 space-y-3">
                    <div className="flex items-center gap-2 text-indigo-900 font-medium">
                        <FileText className="w-5 h-5" />
                        Text to Speak
                    </div>
                    <textarea
                        value={ttsText}
                        onChange={(e) => setTtsText(e.target.value)}
                        rows={3}
                        className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 text-gray-700 placeholder-gray-400"
                        placeholder="Enter text for TTS evaluation..."
                    />
                </div>
            )}

            {/* Configuration Panel */}
            <div className="bg-white rounded-xl shadow-lg p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-6">Configure Comparison</h2>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6 relative">
                    {/* Provider A */}
                    <div className="p-5 bg-gradient-to-br from-blue-50 to-sky-50 rounded-xl border-2 border-blue-200">
                        <div className="flex items-center gap-2 mb-4">
                            <span className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold">A</span>
                            <span className="font-semibold text-blue-900">Provider A</span>
                        </div>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">TTS Provider</label>
                                <select value={providerA} onChange={(e) => { setProviderA(e.target.value); setVoiceA('') }} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 bg-white">
                                    <option value="">Select provider...</option>
                                    {TTS_PROVIDERS.filter(p => p.id !== providerB).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Voices</label>
                                <select
                                    value=""
                                    onChange={(e) => {
                                        const val = e.target.value
                                        if (val && !selectedVoicesA.includes(val)) setSelectedVoicesA([...selectedVoicesA, val])
                                    }}
                                    disabled={!providerA}
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 bg-white"
                                >
                                    <option value="">Add a voice...</option>
                                    {voicesA.filter(v => !selectedVoicesA.includes(v.id)).map(v => <option key={v.id} value={v.id}>{v.name} ({v.gender}, {v.accent})</option>)}
                                </select>
                                <div className="flex flex-wrap gap-2 mt-2">
                                    {activeVoicesA.map(v => (
                                        <div key={v.id} className="flex items-center gap-1 bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full border border-blue-200">
                                            <span>{v.name}</span>
                                            <button onClick={() => setSelectedVoicesA(selectedVoicesA.filter(id => id !== v.id))} className="hover:text-blue-600 rounded-full p-0.5"><X className="w-3 h-3" /></button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            {activeVoicesA.length > 0 && <VoicePreview voice={activeVoicesA[activeVoicesA.length - 1]} isPlaying={playingVoice === activeVoicesA[activeVoicesA.length - 1].id} onPlay={() => handlePlayVoice(activeVoicesA[activeVoicesA.length - 1].id)} colorScheme="blue" />}
                            {providerA && <div className="text-xs text-blue-700 bg-blue-100/80 rounded-lg px-3 py-2 font-medium">💰 Cost: ${TTS_PROVIDERS.find(p => p.id === providerA)?.costPer1M}/1M chars</div>}
                        </div>
                    </div>

                    {/* VS Badge */}
                    <div className="hidden lg:flex absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10">
                        <span className="px-4 py-2 bg-gray-900 text-white rounded-full text-sm font-bold shadow-xl">VS</span>
                    </div>

                    {/* Provider B */}
                    <div className="p-5 bg-gradient-to-br from-purple-50 to-fuchsia-50 rounded-xl border-2 border-purple-200">
                        <div className="flex items-center gap-2 mb-4">
                            <span className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center text-sm font-bold">B</span>
                            <span className="font-semibold text-purple-900">Provider B</span>
                        </div>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">TTS Provider</label>
                                <select value={providerB} onChange={(e) => { setProviderB(e.target.value); setVoiceB('') }} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 bg-white">
                                    <option value="">Select provider...</option>
                                    {TTS_PROVIDERS.filter(p => p.id !== providerA).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Voices</label>
                                <select
                                    value=""
                                    onChange={(e) => {
                                        const val = e.target.value
                                        if (val && !selectedVoicesB.includes(val)) setSelectedVoicesB([...selectedVoicesB, val])
                                    }}
                                    disabled={!providerB}
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 disabled:bg-gray-100 bg-white"
                                >
                                    <option value="">Add a voice...</option>
                                    {voicesB.filter(v => !selectedVoicesB.includes(v.id)).map(v => <option key={v.id} value={v.id}>{v.name} ({v.gender}, {v.accent})</option>)}
                                </select>
                                <div className="flex flex-wrap gap-2 mt-2">
                                    {activeVoicesB.map(v => (
                                        <div key={v.id} className="flex items-center gap-1 bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full border border-purple-200">
                                            <span>{v.name}</span>
                                            <button onClick={() => setSelectedVoicesB(selectedVoicesB.filter(id => id !== v.id))} className="hover:text-purple-600 rounded-full p-0.5"><X className="w-3 h-3" /></button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            {activeVoicesB.length > 0 && <VoicePreview voice={activeVoicesB[activeVoicesB.length - 1]} isPlaying={playingVoice === activeVoicesB[activeVoicesB.length - 1].id} onPlay={() => handlePlayVoice(activeVoicesB[activeVoicesB.length - 1].id)} colorScheme="purple" />}
                            {providerB && <div className="text-xs text-purple-700 bg-purple-100/80 rounded-lg px-3 py-2 font-medium">💰 Cost: ${TTS_PROVIDERS.find(p => p.id === providerB)?.costPer1M}/1M chars</div>}
                        </div>
                    </div>
                </div>

                {/* Additional Config */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                    {evaluationMode === 'agent' && (
                        <>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Scenario</label>
                                <div className="flex gap-2 mb-2">
                                    <button onClick={() => setUseCustomScenario(false)} className={`px-3 py-1.5 text-xs rounded-full transition-colors ${!useCustomScenario ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>Preset</button>
                                    <button onClick={() => setUseCustomScenario(true)} className={`px-3 py-1.5 text-xs rounded-full transition-colors ${useCustomScenario ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>Custom</button>
                                </div>
                                {!useCustomScenario ? (
                                    <select value={selectedScenario} onChange={(e) => setSelectedScenario(e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white">
                                        <option value="">Select scenario...</option>
                                        {scenarios.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
                                    </select>
                                ) : (
                                    <textarea value={customScenario} onChange={(e) => setCustomScenario(e.target.value)} placeholder="Enter custom scenario..." rows={2} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 text-sm bg-white" />
                                )}
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Agent Platform</label>
                                <select value={selectedAgent} onChange={(e) => setSelectedAgent(e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white mt-[34px]">
                                    <option value="">Select platform...</option>
                                    {AGENT_PLATFORMS.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                </select>
                            </div>
                        </>
                    )}
                    <div className={evaluationMode === 'tts' ? "md:col-start-1" : ""}>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Number of Calls</label>
                        <p className="text-xs text-gray-500 mb-2">Max 10 calls per test</p>
                        <div className="flex items-center gap-2 h-[42px]">
                            <input type="range" min={1} max={10} value={numberOfCalls} onChange={(e) => setNumberOfCalls(parseInt(e.target.value))} className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-primary-600" />
                            <span className="text-lg font-bold text-gray-900 w-8 text-center">{numberOfCalls}</span>
                        </div>
                    </div>
                </div>

                <div className="flex justify-center">
                    <Button variant="primary" size="lg" onClick={handleRunTest} disabled={!canRunTest() || isRunning} leftIcon={isRunning ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />} className="px-12">
                        {isRunning ? 'Running Test...' : 'Run Comparison Test'}
                    </Button>
                </div>
            </div>

            {/* Results Section */}
            {results && (
                <div className="bg-white rounded-xl shadow-lg p-6 space-y-6">
                    {/* Winner Banner */}
                    <div className="p-5 bg-gradient-to-r from-green-500 via-emerald-500 to-teal-500 rounded-xl text-white">
                        <div className="flex items-center justify-center gap-3">
                            <Trophy className="w-8 h-8" />
                            <span className="text-xl font-bold">Winner: {results.winner === 'A' ? results.providerA : results.providerB} — {results.winnerPreference}% preference</span>
                        </div>
                    </div>

                    <div className="text-center">
                        <h3 className="text-lg font-semibold text-gray-900">{results.providerA} vs {results.providerB}</h3>
                        <p className="text-sm text-gray-500">Use case: {evaluationMode === 'tts' ? 'Direct TTS' : (useCustomScenario ? 'Custom Scenario' : scenarios.find((s: any) => s.id === selectedScenario)?.name || 'N/A')} • {numberOfCalls} calls</p>
                    </div>

                    {/* Metrics Table */}
                    <div className="overflow-x-auto rounded-lg border border-gray-200">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="bg-gray-50">
                                    <th className="text-left py-3 px-4 font-semibold text-gray-700">Metric</th>
                                    <th className="text-center py-3 px-4 font-semibold text-blue-700">{results.providerA}</th>
                                    <th className="text-center py-3 px-4 font-semibold text-purple-700">{results.providerB}</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                <tr className="hover:bg-gray-50"><td className="py-3 px-4 text-gray-600">Human Preference (simulated)</td><td className="py-3 px-4 text-center font-medium">{results.metrics.blindPreference.A}%</td><td className="py-3 px-4 text-center font-medium">{results.metrics.blindPreference.B}%</td></tr>
                                <tr className="hover:bg-gray-50"><td className="py-3 px-4 text-gray-600">Gibberish Rate</td><td className="py-3 px-4 text-center font-medium">{results.metrics.gibberishRate.A}%</td><td className="py-3 px-4 text-center font-medium">{results.metrics.gibberishRate.B}%</td></tr>
                                <tr className="hover:bg-gray-50"><td className="py-3 px-4 text-gray-600">Pronunciation Accuracy</td><td className="py-3 px-4 text-center font-medium">{results.metrics.pronunciationAccuracy.A}%</td><td className="py-3 px-4 text-center font-medium">{results.metrics.pronunciationAccuracy.B}%</td></tr>
                                <tr className="hover:bg-gray-50"><td className="py-3 px-4 text-gray-600">Emotional Match</td><td className="py-3 px-4 text-center font-medium">{results.metrics.emotionalMatch.A}%</td><td className="py-3 px-4 text-center font-medium">{results.metrics.emotionalMatch.B}%</td></tr>
                                <tr className="hover:bg-gray-50"><td className="py-3 px-4 text-gray-600">MOS (Mean Opinion Score)</td><td className="py-3 px-4 text-center font-medium">{results.metrics.mos.A}</td><td className="py-3 px-4 text-center font-medium">{results.metrics.mos.B}</td></tr>
                                <tr className="hover:bg-gray-50"><td className="py-3 px-4 text-gray-600">Avg TTFB (P95)</td><td className="py-3 px-4 text-center font-medium">{results.metrics.avgTTFB.A}ms</td><td className="py-3 px-4 text-center font-medium">{results.metrics.avgTTFB.B}ms</td></tr>
                            </tbody>
                        </table>
                    </div>

                    {/* Interactive Cost Calculator */}
                    <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-xl p-5 border border-green-200">
                        <h4 className="font-semibold text-green-900 mb-4 flex items-center gap-2">
                            <DollarSign className="w-5 h-5" />
                            Cost Calculator
                        </h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Characters Calculator */}
                            <div className="bg-white rounded-lg p-4 border border-green-100 shadow-sm">
                                <label className="block text-sm font-medium text-gray-700 mb-2">Cost per Characters</label>
                                <div className="flex items-center gap-3 mb-3">
                                    <input type="number" value={costCharacters} onChange={(e) => setCostCharacters(Math.max(0, parseInt(e.target.value) || 0))} className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 text-sm" min={0} step={100000} />
                                    <span className="text-sm text-gray-500">characters</span>
                                </div>
                                <div className="flex items-center justify-between gap-4">
                                    <div className="text-center flex-1">
                                        <p className="text-xs text-gray-500 mb-1">{results.providerA}</p>
                                        <p className="text-xl font-bold text-blue-600">${((costCharacters / 1000000) * results.metrics.costPer1M.A).toFixed(2)}</p>
                                    </div>
                                    <span className="text-gray-300">|</span>
                                    <div className="text-center flex-1">
                                        <p className="text-xs text-gray-500 mb-1">{results.providerB}</p>
                                        <p className="text-xl font-bold text-purple-600">${((costCharacters / 1000000) * results.metrics.costPer1M.B).toFixed(2)}</p>
                                    </div>
                                </div>
                                <div className="mt-3 flex gap-2 flex-wrap">
                                    {[100000, 500000, 1000000, 5000000, 10000000].map(val => (
                                        <button key={val} onClick={() => setCostCharacters(val)} className={`px-2 py-1 text-xs rounded-full transition-colors ${costCharacters === val ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                                            {val >= 1000000 ? `${val / 1000000}M` : `${val / 1000}K`}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Minutes Calculator */}
                            <div className="bg-white rounded-lg p-4 border border-green-100 shadow-sm">
                                <label className="block text-sm font-medium text-gray-700 mb-2">Cost per Minutes</label>
                                <div className="flex items-center gap-3 mb-3">
                                    <input type="number" value={costMinutes} onChange={(e) => setCostMinutes(Math.max(0, parseInt(e.target.value) || 0))} className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 text-sm" min={0} step={10000} />
                                    <span className="text-sm text-gray-500">minutes</span>
                                </div>
                                <div className="flex items-center justify-between gap-4">
                                    <div className="text-center flex-1">
                                        <p className="text-xs text-gray-500 mb-1">{results.providerA}</p>
                                        <p className="text-xl font-bold text-blue-600">${((costMinutes / 100000) * results.metrics.costPer100kMin.A).toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                                    </div>
                                    <span className="text-gray-300">|</span>
                                    <div className="text-center flex-1">
                                        <p className="text-xs text-gray-500 mb-1">{results.providerB}</p>
                                        <p className="text-xl font-bold text-purple-600">${((costMinutes / 100000) * results.metrics.costPer100kMin.B).toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                                    </div>
                                </div>
                                <div className="mt-3 flex gap-2 flex-wrap">
                                    {[10000, 50000, 100000, 500000, 1000000].map(val => (
                                        <button key={val} onClick={() => setCostMinutes(val)} className={`px-2 py-1 text-xs rounded-full transition-colors ${costMinutes === val ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                                            {val >= 1000000 ? `${val / 1000000}M` : `${val / 1000}K`}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Savings Summary */}
                        <div className="mt-4 p-3 bg-white rounded-lg border border-green-100">
                            <div className="flex items-center justify-center gap-4 text-sm flex-wrap">
                                <span className="text-gray-600">Potential savings:</span>
                                <span className="font-bold text-green-600">
                                    ${Math.abs(((costCharacters / 1000000) * results.metrics.costPer1M.A) - ((costCharacters / 1000000) * results.metrics.costPer1M.B)).toFixed(2)} / {costCharacters >= 1000000 ? `${costCharacters / 1000000}M` : `${costCharacters / 1000}K`} chars
                                </span>
                                <span className="text-gray-400">|</span>
                                <span className="font-bold text-green-600">
                                    ${Math.abs(((costMinutes / 100000) * results.metrics.costPer100kMin.A) - ((costMinutes / 100000) * results.metrics.costPer100kMin.B)).toLocaleString(undefined, { maximumFractionDigits: 0 })} / {costMinutes >= 1000000 ? `${costMinutes / 1000000}M` : `${costMinutes / 1000}K`} mins
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Call Recordings */}
                    <div className="bg-gray-50 rounded-xl p-4">
                        <h4 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
                            <FileText className="w-5 h-5 text-gray-600" />
                            Call Recordings & Transcripts
                        </h4>
                        <div className="space-y-3 max-h-[600px] overflow-y-auto">
                            {results.callRecordings.map((call) => (
                                <details key={call.id} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                                    <summary className="flex items-center justify-between p-4 cursor-pointer hover:bg-gray-50">
                                        <div className="flex items-center gap-4">
                                            <span className="text-sm font-medium text-gray-700">Call #{call.callNumber}</span>
                                            <span className="text-xs text-gray-500">{Math.floor(call.duration / 60)}:{(call.duration % 60).toString().padStart(2, '0')}</span>
                                            <span className="text-xs text-gray-400">TTFB: A={call.metrics.ttfb.A}ms / B={call.metrics.ttfb.B}ms</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button onClick={(e) => { e.preventDefault(); handlePlayVoice(`${call.id}-A`) }} className="flex items-center gap-1 px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg text-xs font-medium hover:bg-blue-200"><Play className="w-3 h-3" /> Play A</button>
                                            <button onClick={(e) => { e.preventDefault(); handlePlayVoice(`${call.id}-B`) }} className="flex items-center gap-1 px-3 py-1.5 bg-purple-100 text-purple-700 rounded-lg text-xs font-medium hover:bg-purple-200"><Play className="w-3 h-3" /> Play B</button>
                                        </div>
                                    </summary>
                                    <div className="border-t border-gray-100">
                                        {/* Per-Call Metrics */}
                                        <div className="p-4 bg-gradient-to-r from-blue-50 via-white to-purple-50">
                                            <h5 className="text-xs font-semibold text-gray-700 mb-3 uppercase tracking-wide">Call Metrics</h5>
                                            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                                                <div className="bg-white rounded-lg p-3 border border-gray-100 shadow-sm">
                                                    <p className="text-xs text-gray-500 mb-1">TTFB</p>
                                                    <div className="flex items-baseline gap-2">
                                                        <span className="text-sm font-bold text-blue-600">{call.metrics.ttfb.A}ms</span>
                                                        <span className="text-xs text-gray-400">vs</span>
                                                        <span className="text-sm font-bold text-purple-600">{call.metrics.ttfb.B}ms</span>
                                                    </div>
                                                </div>
                                                <div className="bg-white rounded-lg p-3 border border-gray-100 shadow-sm">
                                                    <p className="text-xs text-gray-500 mb-1">Gibberish Rate</p>
                                                    <div className="flex items-baseline gap-2">
                                                        <span className="text-sm font-bold text-blue-600">{call.metrics.gibberishRate.A}%</span>
                                                        <span className="text-xs text-gray-400">vs</span>
                                                        <span className="text-sm font-bold text-purple-600">{call.metrics.gibberishRate.B}%</span>
                                                    </div>
                                                </div>
                                                <div className="bg-white rounded-lg p-3 border border-gray-100 shadow-sm">
                                                    <p className="text-xs text-gray-500 mb-1">Pronunciation</p>
                                                    <div className="flex items-baseline gap-2">
                                                        <span className="text-sm font-bold text-blue-600">{call.metrics.pronunciationAccuracy.A}%</span>
                                                        <span className="text-xs text-gray-400">vs</span>
                                                        <span className="text-sm font-bold text-purple-600">{call.metrics.pronunciationAccuracy.B}%</span>
                                                    </div>
                                                </div>
                                                <div className="bg-white rounded-lg p-3 border border-gray-100 shadow-sm">
                                                    <p className="text-xs text-gray-500 mb-1">Emotional Match</p>
                                                    <div className="flex items-baseline gap-2">
                                                        <span className="text-sm font-bold text-blue-600">{call.metrics.emotionalMatch.A}%</span>
                                                        <span className="text-xs text-gray-400">vs</span>
                                                        <span className="text-sm font-bold text-purple-600">{call.metrics.emotionalMatch.B}%</span>
                                                    </div>
                                                </div>
                                                <div className="bg-white rounded-lg p-3 border border-gray-100 shadow-sm">
                                                    <p className="text-xs text-gray-500 mb-1">MOS Score</p>
                                                    <div className="flex items-baseline gap-2">
                                                        <span className="text-sm font-bold text-blue-600">{call.metrics.mos.A}</span>
                                                        <span className="text-xs text-gray-400">vs</span>
                                                        <span className="text-sm font-bold text-purple-600">{call.metrics.mos.B}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                        {/* Transcript */}
                                        <div className="p-4 bg-gray-50">
                                            <h5 className="text-xs font-semibold text-gray-700 mb-3 uppercase tracking-wide">Transcript</h5>
                                            <div className="space-y-3">
                                                {call.transcripts.map((t, idx) => (
                                                    <div key={idx} className="space-y-2">
                                                        <div className="flex gap-3">
                                                            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center"><Mic className="w-3 h-3 text-blue-600" /></div>
                                                            <div className="flex-1">
                                                                <p className="text-xs text-blue-600 font-medium mb-0.5">{t.customerLine ? 'Agent' : 'TTS Output'}</p>
                                                                <p className="text-sm text-gray-700">{t.agentLine}</p>
                                                                {call.voiceSamples && (
                                                                    <div className="grid grid-cols-1 gap-2 mt-2">
                                                                        {call.voiceSamples.A.map((v: any) => (
                                                                            <div key={v.id} className="text-xs bg-blue-50 p-2 rounded border border-blue-100 flex items-center gap-2">
                                                                                <span className="font-bold text-blue-700 w-6">A</span>
                                                                                <span className="text-blue-900 font-medium">{v.name}</span>
                                                                                <div onClick={() => handlePlayVoice(`${call.id}-A-${v.id}`)} className="ml-auto cursor-pointer p-1 hover:bg-blue-200 rounded-full transition-colors">
                                                                                    {playingVoice === `${call.id}-A-${v.id}` ? <Loader2 className="w-3 h-3 text-blue-600 animate-spin" /> : <Play className="w-3 h-3 text-blue-600" />}
                                                                                </div>
                                                                            </div>
                                                                        ))}
                                                                        {call.voiceSamples.B.map((v: any) => (
                                                                            <div key={v.id} className="text-xs bg-purple-50 p-2 rounded border border-purple-100 flex items-center gap-2">
                                                                                <span className="font-bold text-purple-700 w-6">B</span>
                                                                                <span className="text-purple-900 font-medium">{v.name}</span>
                                                                                <div onClick={() => handlePlayVoice(`${call.id}-B-${v.id}`)} className="ml-auto cursor-pointer p-1 hover:bg-purple-200 rounded-full transition-colors">
                                                                                    {playingVoice === `${call.id}-B-${v.id}` ? <Loader2 className="w-3 h-3 text-purple-600 animate-spin" /> : <Play className="w-3 h-3 text-purple-600" />}
                                                                                </div>
                                                                            </div>
                                                                        ))}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                        {t.customerLine && (
                                                            <div className="flex gap-3 ml-8">
                                                                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center"><Volume2 className="w-3 h-3 text-gray-600" /></div>
                                                                <div className="flex-1"><p className="text-xs text-gray-500 font-medium mb-0.5">Customer</p><p className="text-sm text-gray-600">{t.customerLine}</p></div>
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </details>
                            ))}
                        </div>
                    </div>

                    {/* Recommendation */}
                    <div className="p-5 bg-gradient-to-r from-green-50 via-emerald-50 to-teal-50 rounded-xl border border-green-200">
                        <h4 className="font-semibold text-green-800 mb-2 flex items-center gap-2"><Trophy className="w-5 h-5" /> Recommendation</h4>
                        <p className="text-green-700">Based on quality metrics and cost analysis, we recommend <strong>{results.winner === 'A' ? results.providerA : results.providerB}</strong> for your use case.</p>
                    </div>

                    {/* Actions */}
                    <div className="flex justify-center gap-4">
                        <Button variant="ghost" leftIcon={<Share2 className="w-4 h-4" />} onClick={() => navigator.clipboard.writeText(window.location.href)}>Share Results</Button>
                        <Button variant="primary" leftIcon={<RotateCcw className="w-4 h-4" />} onClick={resetPlayground}>Run New Comparison</Button>
                    </div>
                </div>
            )}


        </div>
    )
}
