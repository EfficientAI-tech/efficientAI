import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAgentStore } from '../../../store/agentStore'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { Play, X, Phone, PhoneOff, RefreshCw, Mic, Bot, PhoneCall, Trash2, AlertTriangle, CheckSquare, Square, Bookmark, BookmarkCheck, Activity, Search } from 'lucide-react'
import Button from '../../../components/Button'
import TableListPagination from '../../../components/TableListPagination'
import { useToast } from '../../../hooks/useToast'
import { RetellWebClient } from 'retell-client-js-sdk'
import Vapi from '@vapi-ai/web'
import { Conversation } from '@elevenlabs/client'
import VoiceAgent from '../../../components/VoiceAgent'
import GenericVoiceWSClient from '../../../components/GenericVoiceWSClient'
import TraceDetailDrawer from '../../../components/call-recordings/TraceDetailDrawer'
import { getProtocolById } from '../../../lib/wsProtocols'
import { prefetchCallRecordingQuery, refreshCallRecordingQueries, warmCallRecordingQueryFromList } from '../../../lib/callRecordingQuery'
import { prefetchCallRecordingAudio, prefetchEvaluatorRecordingAudio } from '../../../lib/waveformAudioCache'
import { getIntegrationPlatformLogo } from '../../../config/providers'
import { IntegrationPlatform } from '../../../types/api'

const PLAYGROUND_LIST_PAGE_SIZE = 10

function paginateList<T>(items: T[], page: number, pageSize: number) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const safePage = Math.min(Math.max(1, page), pageCount)
  const start = (safePage - 1) * pageSize
  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    pageCount,
    total: items.length,
  }
}

function PlaygroundListToolbar({
  search,
  onSearchChange,
  statusOptions,
  statusFilter,
  onStatusChange,
}: {
  search: string
  onSearchChange: (value: string) => void
  statusOptions: Array<{ value: string; label: string }>
  statusFilter: string
  onStatusChange: (value: string) => void
}) {
  return (
    <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-1">
        {statusOptions.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => onStatusChange(value)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              statusFilter === value
                ? 'border-gray-300 bg-gray-200 text-gray-800'
                : 'border-transparent text-gray-600 hover:bg-gray-100'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="relative w-full sm:w-auto">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
        <input
          type="search"
          placeholder="Search call ID…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full rounded-lg border border-gray-300 py-1.5 pl-9 pr-3 text-sm focus:border-primary-500 focus:ring-primary-500 sm:w-56"
        />
      </div>
    </div>
  )
}

// Type for RetellWebClient - using the actual SDK methods
type RetellWebClientWithMethods = RetellWebClient & {
  startCall: (config: {
    accessToken: string;
    sampleRate?: number;
    captureDeviceId?: string;
    playbackDeviceId?: string;
    emitRawAudioSamples?: boolean;
    callId?: string;
  }) => Promise<void>
  stopCall: () => void
}

export default function AgentPlayground() {
  const { selectedAgent } = useAgentStore()
  const { showToast, ToastContainer } = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [showTestModal, setShowTestModal] = useState(false)
  const [selectedTestType, setSelectedTestType] = useState<'test_agent' | 'voice_ai_agent' | null>(null)
  const [testPersonaId, setTestPersonaId] = useState('')
  const [testScenarioId, setTestScenarioId] = useState('')
  const [runPostCallEvaluation, setRunPostCallEvaluation] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [isRefreshingStatus, setIsRefreshingStatus] = useState(false)
  const [transcripts, setTranscripts] = useState<Array<{ role: 'user' | 'agent', content: string }>>([])

  const retellClientRef = useRef<RetellWebClientWithMethods | null>(null)
  const vapiClientRef = useRef<any>(null)
  const elevenLabsConversationRef = useRef<any>(null)
  const smallestClientRef = useRef<any>(null)
  const currentCallShortIdRef = useRef<string | null>(null)

  const userInitiatedDisconnectRef = useRef(false)

  // Fetch integrations to check if agent has Retell integration
  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  // Fetch full agent details including integration info
  const { data: fullAgent } = useQuery({
    queryKey: ['agent', selectedAgent?.id],
    queryFn: () => apiClient.getAgent(selectedAgent?.id || ''),
    enabled: !!selectedAgent?.id,
  })


  // Fetch test voice agent evaluation results (playground results only, excluding Voice AI agent results)
  const { data: testVoiceAgentList, refetch: refetchTestResults } = useQuery({
    queryKey: ['test-voice-agent-results'],
    queryFn: async () => {
      return await apiClient.listEvaluatorResults(undefined, true, true)
    },
  })
  const testVoiceAgentResults = testVoiceAgentList?.items ?? []

  // Fetch call recordings (for Voice AI Agents tab)
  const { data: callRecordings = [], refetch: refetchCallRecordings } = useQuery({
    queryKey: ['call-recordings'],
    queryFn: () => apiClient.listCallRecordings(),
    // Refetch every 5 seconds if there are any evaluations in progress
    refetchInterval: (query) => {
      const data = query.state.data as any[]
      if (data && Array.isArray(data)) {
        const hasInProgress = data.some((recording: any) => 
          recording.evaluation_status && 
          ['queued', 'transcribing', 'evaluating'].includes(recording.evaluation_status)
        )
        return hasInProgress ? 5000 : false
      }
      return false
    },
  })

  // Check S3 storage status for warning
  const { data: s3Status } = useQuery({
    queryKey: ['s3-status'],
    queryFn: () => apiClient.getS3Status(),
    staleTime: 60_000,
  })

  const [activeTab, setActiveTab] = useState<'test_agents' | 'voice_ai_agents' | 'custom_websocket'>('voice_ai_agents')
  const [testAgentsPage, setTestAgentsPage] = useState(1)
  const [voiceAiPage, setVoiceAiPage] = useState(1)
  const [customWsPage, setCustomWsPage] = useState(1)
  const [listSearchQuery, setListSearchQuery] = useState('')
  const [listStatusFilter, setListStatusFilter] = useState('all')
  const [customWebsocketUrl, setCustomWebsocketUrl] = useState('')

  // Saved WebSocket URLs (persisted in localStorage)
  type SavedWsUrl = { id: string; label: string; url: string; createdAt: string }
  const SAVED_WS_KEY = 'efficientai-saved-ws-urls'
  const loadSavedUrls = (): SavedWsUrl[] => {
    try { return JSON.parse(localStorage.getItem(SAVED_WS_KEY) || '[]') } catch { return [] }
  }
  const [savedWsUrls, setSavedWsUrls] = useState<SavedWsUrl[]>(loadSavedUrls)
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveLabel, setSaveLabel] = useState('')

  const persistSavedUrls = (urls: SavedWsUrl[]) => {
    setSavedWsUrls(urls)
    localStorage.setItem(SAVED_WS_KEY, JSON.stringify(urls))
  }
  const handleSaveUrl = () => {
    const url = customWebsocketUrl.trim()
    if (!url) return
    const label = saveLabel.trim() || url
    const entry: SavedWsUrl = { id: crypto.randomUUID(), label, url, createdAt: new Date().toISOString() }
    persistSavedUrls([entry, ...savedWsUrls])
    setSaveLabel('')
    setShowSaveForm(false)
  }
  const handleDeleteSavedUrl = (id: string) => {
    persistSavedUrls(savedWsUrls.filter((s) => s.id !== id))
  }
  const isCurrentUrlSaved = savedWsUrls.some((s) => s.url === customWebsocketUrl.trim())
  const [selectedCallIds, setSelectedCallIds] = useState<Set<string>>(new Set())
  const [isDeletingSelected, setIsDeletingSelected] = useState(false)
  const [selectedTestResultIds, setSelectedTestResultIds] = useState<Set<string>>(new Set())
  const [otlpTraceResultId, setOtlpTraceResultId] = useState<string | null>(null)
  const isVoiceAiProviderRecording = (recording: { provider_platform?: string | null }) => {
    const platform = (recording.provider_platform || '').toLowerCase()
    return (
      platform === IntegrationPlatform.RETELL ||
      platform === IntegrationPlatform.VAPI ||
      platform === IntegrationPlatform.ELEVENLABS ||
      platform === IntegrationPlatform.SMALLEST ||
      platform === 'retell' ||
      platform === 'vapi' ||
      platform === 'elevenlabs' ||
      platform === 'smallest'
    )
  }
  const [isDeletingSelectedTests, setIsDeletingSelectedTests] = useState(false)


  // Find the integration for the agent
  const agentIntegration = fullAgent?.voice_ai_integration_id
    ? integrations.find((int: any) => int.id === fullAgent.voice_ai_integration_id)
    : null

  const isRetellAgent = agentIntegration?.platform === 'retell'
  const isVapiAgent = agentIntegration?.platform === 'vapi'
  const isElevenLabsAgent = agentIntegration?.platform === 'elevenlabs'
  const isSmallestAgent = agentIntegration?.platform === 'smallest'

  const hasVoiceAIIntegration = Boolean(
    fullAgent?.voice_ai_integration_id &&
    fullAgent?.voice_ai_agent_id &&
    (isRetellAgent || isVapiAgent || isElevenLabsAgent || isSmallestAgent)
  )
  // Playground web-call testing via Retell/Vapi/ElevenLabs/Smallest is independent
  // of the agent's production call_medium (phone_call vs web_call).
  const canMakeCall = hasVoiceAIIntegration

  // Check if agent has Test Agent capabilities (voice bundle with STT/TTS/LLM)
  const hasTestAgent = fullAgent?.voice_bundle_id != null
  const hasVoiceAIAgent = hasVoiceAIIntegration

  const { data: testPersonas = [] } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
    enabled: selectedTestType === 'test_agent',
  })

  const { data: testScenarios = [] } = useQuery({
    queryKey: ['scenarios', selectedAgent?.id],
    queryFn: () => apiClient.listScenarios(0, 100, selectedAgent?.id),
    enabled: selectedTestType === 'test_agent' && !!selectedAgent?.id,
  })

  const { data: testAgentVoiceBundle } = useQuery({
    queryKey: ['voicebundle', fullAgent?.voice_bundle_id],
    queryFn: () => apiClient.getVoiceBundle(fullAgent!.voice_bundle_id!),
    enabled: selectedTestType === 'test_agent' && !!fullAgent?.voice_bundle_id,
  })

  const testVoiceBundleTtsProvider = testAgentVoiceBundle?.tts_provider
    ? String(testAgentVoiceBundle.tts_provider).toLowerCase()
    : null

  const eligibleTestPersonas = testVoiceBundleTtsProvider
    ? testPersonas.filter((p: any) => p.tts_provider?.toLowerCase() === testVoiceBundleTtsProvider)
    : testPersonas

  const selectedTestPersona = eligibleTestPersonas.find((p: any) => p.id === testPersonaId)
  const selectedTestScenario = testScenarios.find((s: any) => s.id === testScenarioId)
  const testSetupComplete = Boolean(testPersonaId && testScenarioId)

  // Initialize Clients when modal opens
  useEffect(() => {
    if (showModal && canMakeCall) {
      if (isRetellAgent && !retellClientRef.current) {
        const client = new RetellWebClient() as unknown as RetellWebClientWithMethods
        console.log('RetellWebClient initialized')
        retellClientRef.current = client
      } else if (isVapiAgent && !vapiClientRef.current && agentIntegration?.public_key) {
        const client = new Vapi(agentIntegration.public_key)
        console.log('Vapi client initialized')
        vapiClientRef.current = client
      }
      // ElevenLabs: no persistent client — sessions are created on connect
    }

    return () => {
      if (retellClientRef.current) {
        try {
          retellClientRef.current.stopCall()
        } catch (e) {
          console.error('Error stopping Retell call on cleanup:', e)
        }
      }
      if (vapiClientRef.current) {
        try {
          vapiClientRef.current.stop()
        } catch (e) {
          console.error('Error stopping Vapi call on cleanup:', e)
        }
      }
      if (elevenLabsConversationRef.current) {
        try {
          elevenLabsConversationRef.current.endSession()
        } catch (e) {
          console.error('Error ending ElevenLabs session on cleanup:', e)
        }
        elevenLabsConversationRef.current = null
      }
      if (smallestClientRef.current) {
        try {
          smallestClientRef.current.stopSession()
        } catch (e) {
          console.error('Error stopping Smallest session on cleanup:', e)
        }
        smallestClientRef.current = null
      }
    }
  }, [showModal, canMakeCall, isRetellAgent, isVapiAgent, isElevenLabsAgent, isSmallestAgent, agentIntegration?.public_key])

  const handleConnect = async () => {
    if (!canMakeCall || !fullAgent?.id) {
      showToast('Agent is not configured for web calls', 'error')
      return
    }

    setIsConnecting(true)
    setTranscripts([])

    if (isRetellAgent) {
      if (!retellClientRef.current) {
        retellClientRef.current = new RetellWebClient() as unknown as RetellWebClientWithMethods
      }

      const client = retellClientRef.current

      try {
        // IMPORTANT: Request microphone permission FIRST, before creating the web call
        try {
          const testStream = await navigator.mediaDevices.getUserMedia({ audio: true })
          console.log('Microphone access granted')
          testStream.getTracks().forEach(track => track.stop())
        } catch (micError: any) {
          console.error('Microphone permission denied:', micError)
          setIsConnecting(false)
          showToast('Microphone permission is required for voice calls', 'error')
          return
        }

        // Set up event handlers
        client.on('call_started', () => {
          console.log('Retell call started')
          setIsConnected(true)
          setIsConnecting(false)
          showToast('Connected to agent', 'success')
        })

        // Handle updates (transcripts)
        client.on('update', (update: any) => {
          if (update.transcript) {
            // Retell sends transcript as an array of {role, content, words} objects
            // We need to convert this to our simpler format
            const transcriptArray = Array.isArray(update.transcript) 
              ? update.transcript 
              : [{ role: update.role || 'agent', content: update.transcript }]
            
            setTranscripts(
              transcriptArray
                .filter((msg: any) => msg && msg.content && typeof msg.content === 'string')
                .map((msg: any) => ({
                  role: msg.role === 'user' ? 'user' as const : 'agent' as const,
                  content: msg.content
                }))
            )
          }
        })

        client.on('call_ended', (data?: any) => {
          console.log('Retell call ended', data)
          setIsConnected(false)
          setIsConnecting(false)
          if (!userInitiatedDisconnectRef.current) {
            const reason = data?.reason || data?.code || 'Unknown reason'
            showToast(`Call ended: ${reason}`)
          }
          userInitiatedDisconnectRef.current = false

          // Trigger refresh of metrics
          if (currentCallShortIdRef.current) {
            refreshCallRecordingQueries(queryClient, currentCallShortIdRef.current).catch((err) =>
              console.error('Failed to refresh metrics', err),
            )
          }
        })

        client.on('error', (error: any) => {
          console.error('Retell error:', error)
          setIsConnecting(false)
          setIsConnected(false)
          showToast(`Error: ${error?.message || 'Unknown error'}`, 'error')
        })

        // Create web call
        console.log('Creating web call...')
        const webCallResponse = await apiClient.createWebCall({
          agent_id: fullAgent.id,
          metadata: {},
          retell_llm_dynamic_variables: {},
          custom_sip_headers: {},
          ui_surface: 'agent_playground',
        })

        if (!webCallResponse.call_id || !webCallResponse.access_token) {
          throw new Error('No call_id or access_token received')
        }

        if (webCallResponse.call_short_id) {
          currentCallShortIdRef.current = webCallResponse.call_short_id
        }

        // Start call
        await client.startCall({
          accessToken: webCallResponse.access_token,
          callId: webCallResponse.call_id,
          sampleRate: webCallResponse.sample_rate || 24000,
        })
      } catch (error: any) {
        console.error('Failed to connect Retell:', error)
        setIsConnecting(false)
        setIsConnected(false)
        const detail = error?.response?.data?.detail || error?.message || 'Unknown error'
        showToast(`Failed to connect: ${detail}`, 'error')
      }
    } else if (isVapiAgent) {
      const client = vapiClientRef.current
      if (!client) {
        setIsConnecting(false)
        showToast('Vapi client not initialized', 'error')
        return
      }

      try {
        // Create backend record for Vapi call
        console.log('Creating Vapi web call record...')
        const webCallResponse = await apiClient.createWebCall({
          agent_id: fullAgent.id,
          metadata: {},
          ui_surface: 'agent_playground',
        })

        if (webCallResponse.call_short_id) {
          currentCallShortIdRef.current = webCallResponse.call_short_id
        }

        // Vapi Event Handlers
        client.on('call-start', async (call: any) => {
          console.log('Vapi call started', call)
          setIsConnected(true)
          setIsConnecting(false)
          showToast('Connected to agent', 'success')

          // Update backend with Vapi Call ID
          if (currentCallShortIdRef.current && call?.id) {
            try {
              await apiClient.updateCallRecording(currentCallShortIdRef.current, call.id)
              console.log('Updated call recording with Vapi ID:', call.id)
            } catch (err) {
              console.error('Failed to update call recording provider ID', err)
            }
          }
        })

        // Vapi Transcription Handling
        client.on('message', (message: any) => {
          if (message.type === 'transcript' && message.transcriptType === 'final') {
            const role = message.role === 'user' ? 'user' : 'agent'
            setTranscripts(prev => [...prev, { role, content: message.transcript }])
          }
        })

        client.on('call-end', async (call: any) => {
          console.log('Vapi call ended', call)
          setIsConnected(false)
          setIsConnecting(false)
          if (!userInitiatedDisconnectRef.current) {
            showToast('Call ended')
          }
          userInitiatedDisconnectRef.current = false

          // Ensure we have provider ID before refreshing
          if (currentCallShortIdRef.current) {
            if (call?.id) {
              try {
                await apiClient.updateCallRecording(currentCallShortIdRef.current, call.id)
              } catch (e) {
                console.error('Failed to update call recording on end', e)
              }
            }

            refreshCallRecordingQueries(queryClient, currentCallShortIdRef.current).catch((err) =>
              console.error('Failed to refresh metrics', err),
            )
          }
        })

        client.on('error', (error: any) => {
          console.error('Vapi error:', error)
          setIsConnecting(false)
          setIsConnected(false)
          showToast(`Error: ${error?.message || 'Unknown error'}`, 'error')
        })

        // Start Call
        // Note: For Vapi, we just need the assistant ID (voice_ai_agent_id)
        console.log('Starting Vapi call...')
        const vapiCall = await client.start(fullAgent.voice_ai_agent_id)
        console.log('Vapi start returned:', vapiCall)

        // Try to get ID from return value immediately
        if (currentCallShortIdRef.current && vapiCall?.id) {
          try {
            await apiClient.updateCallRecording(currentCallShortIdRef.current, vapiCall.id)
            console.log('Updated call recording with Vapi ID (from start):', vapiCall.id)
          } catch (err) {
            console.error('Failed to update call recording provider ID', err)
          }
        }
      } catch (error: any) {
        console.error('Failed to connect Vapi:', error)
        setIsConnecting(false)
        setIsConnected(false)
        const detail = error?.response?.data?.detail || error?.message || 'Unknown error'
        showToast(`Failed to connect: ${detail}`, 'error')
      }
    } else if (isElevenLabsAgent) {
      try {
        // Request microphone permission first
        try {
          const testStream = await navigator.mediaDevices.getUserMedia({ audio: true })
          testStream.getTracks().forEach(track => track.stop())
        } catch (micError: any) {
          console.error('Microphone permission denied:', micError)
          setIsConnecting(false)
          showToast('Microphone permission is required for voice calls', 'error')
          return
        }

        // Create backend record and get signed URL
        console.log('Creating ElevenLabs web call...')
        const webCallResponse = await apiClient.createWebCall({
          agent_id: fullAgent.id,
          metadata: {},
          ui_surface: 'agent_playground',
        })

        if (webCallResponse.call_short_id) {
          currentCallShortIdRef.current = webCallResponse.call_short_id
        }

        const signedUrl = webCallResponse.signed_url
        if (!signedUrl) {
          throw new Error('No signed_url received from backend')
        }

        console.log('Starting ElevenLabs conversation session with signed URL...')

        let elevenLabsConversationIdStored = false

        const conversationInstance = await Conversation.startSession({
          signedUrl,
          onConnect: () => {
            console.log('ElevenLabs conversation connected')
            setIsConnected(true)
            setIsConnecting(false)
            showToast('Connected to agent', 'success')
          },
          onDisconnect: () => {
            console.log('ElevenLabs conversation disconnected')
            setIsConnected(false)
            setIsConnecting(false)
            elevenLabsConversationRef.current = null
            if (!userInitiatedDisconnectRef.current) {
              showToast('Call ended')
            }
            userInitiatedDisconnectRef.current = false

            // Only refresh if we successfully stored the conversation ID,
            // otherwise the backend has no provider_call_id to fetch metrics for
            if (currentCallShortIdRef.current && elevenLabsConversationIdStored) {
              const callShortId = currentCallShortIdRef.current
              // ElevenLabs transitions through "processing" before "done",
              // so wait a few seconds before requesting metrics
              setTimeout(() => {
                refreshCallRecordingQueries(queryClient, callShortId).catch((err) =>
                  console.error('Failed to refresh metrics', err),
                )
              }, 5000)
            }
          },
          onMessage: (message: any) => {
            console.log('ElevenLabs message:', message)
            if (message?.source && message?.message) {
              const role = message.source === 'user' ? 'user' as const : 'agent' as const
              setTranscripts(prev => [...prev, { role, content: message.message }])
            }
          },
          onError: (error: any) => {
            console.error('ElevenLabs onError:', error)
            setIsConnecting(false)
            setIsConnected(false)
            const msg = typeof error === 'string' ? error : error?.message || JSON.stringify(error)
            showToast(`ElevenLabs error: ${msg}`, 'error')
          },
          onStatusChange: (status: any) => {
            console.log('ElevenLabs status change:', status)
          },
        })

        elevenLabsConversationRef.current = conversationInstance

        // Get conversation ID AFTER startSession resolves (the instance is now available)
        try {
          const conversationId = conversationInstance?.getId()
          console.log('ElevenLabs conversation ID:', conversationId)
          if (currentCallShortIdRef.current && conversationId) {
            await apiClient.updateCallRecording(currentCallShortIdRef.current, conversationId)
            elevenLabsConversationIdStored = true
            console.log('Updated call recording with ElevenLabs conversation ID:', conversationId)
          } else {
            console.warn('Missing callShortId or conversationId for ElevenLabs update', {
              callShortId: currentCallShortIdRef.current,
              conversationId,
            })
          }
        } catch (e) {
          console.error('Failed to update call recording with ElevenLabs conversation ID:', e)
        }
      } catch (error: any) {
        console.error('Failed to connect ElevenLabs:', error)
        setIsConnecting(false)
        setIsConnected(false)
        const detail = error?.response?.data?.detail
          || (typeof error === 'string' ? error : error?.message || JSON.stringify(error))
        showToast(`Failed to connect: ${detail}`, 'error')
      }
    } else if (isSmallestAgent) {
      try {
        const { AtomsClient } = await import('atoms-client-sdk')

        // Request microphone permission first
        try {
          const testStream = await navigator.mediaDevices.getUserMedia({ audio: true })
          testStream.getTracks().forEach(track => track.stop())
        } catch (micError: any) {
          console.error('Microphone permission denied:', micError)
          setIsConnecting(false)
          showToast('Microphone permission is required for voice calls', 'error')
          return
        }

        const webCallResponse = await apiClient.createWebCall({
          agent_id: fullAgent.id,
          metadata: {},
          ui_surface: 'agent_playground',
        })

        if (webCallResponse.call_short_id) {
          currentCallShortIdRef.current = webCallResponse.call_short_id
        }

        if (!webCallResponse.access_token || !webCallResponse.host) {
          throw new Error('Smallest webcall response missing access token or host')
        }

        const client = new AtomsClient()
        smallestClientRef.current = client

        client.on('session_started', () => {
          console.log('Smallest webcall connected')
          setIsConnected(true)
          setIsConnecting(false)
          showToast('Connected to agent', 'success')
        })
        client.on('session_ended', () => {
          console.log('Smallest webcall disconnected')
          setIsConnected(false)
          setIsConnecting(false)
          if (!userInitiatedDisconnectRef.current) {
            showToast('Call ended')
          }
          userInitiatedDisconnectRef.current = false

          if (currentCallShortIdRef.current) {
            const callShortId = currentCallShortIdRef.current
            setTimeout(() => {
              refreshCallRecordingQueries(queryClient, callShortId).catch((err) =>
                console.error('Failed to refresh metrics', err),
              )
            }, 3000)
          }
        })
        client.on('transcript', (data: any) => {
          const content = data?.text
          if (content && typeof content === 'string') {
            setTranscripts(prev => [...prev, { role: 'agent', content }])
          }
        })
        client.on('error', (errorMessage: string) => {
          console.error('Smallest SDK error:', errorMessage)
        })

        await client.startSession({
          accessToken: webCallResponse.access_token,
          host: webCallResponse.host,
          mode: 'webcall',
        })
        await client.startAudioPlayback()
      } catch (error: any) {
        console.error('Failed to connect Smallest:', error)
        if (smallestClientRef.current) {
          try {
            smallestClientRef.current.stopSession()
          } catch {
            // ignore cleanup errors
          }
          smallestClientRef.current = null
        }
        setIsConnecting(false)
        setIsConnected(false)
        const detail = error?.response?.data?.detail
          || (typeof error === 'string' ? error : error?.message || JSON.stringify(error))
        showToast(`Failed to connect: ${detail}`, 'error')
      }
    }
  }

  const handleDisconnect = async () => {
    userInitiatedDisconnectRef.current = true

    if (isRetellAgent && retellClientRef.current) {
      try {
        retellClientRef.current.stopCall()
      } catch (error: any) {
        console.error('Failed to disconnect Retell:', error)
      }
    } else if (isVapiAgent && vapiClientRef.current) {
      try {
        vapiClientRef.current.stop()
      } catch (error: any) {
        console.error('Failed to disconnect Vapi:', error)
      }
    } else if (isElevenLabsAgent && elevenLabsConversationRef.current) {
      try {
        await elevenLabsConversationRef.current.endSession()
        elevenLabsConversationRef.current = null
      } catch (error: any) {
        console.error('Failed to disconnect ElevenLabs:', error)
      }
    } else if (isSmallestAgent && smallestClientRef.current) {
      try {
        smallestClientRef.current.stopSession()
        smallestClientRef.current = null
      } catch (error: any) {
        console.error('Failed to disconnect Smallest:', error)
      }
    }

    setIsConnected(false)
    showToast('Disconnected', 'success')
  }

  const handleCloseModal = () => {
    if (isConnected) {
      handleDisconnect()
    }
    setShowModal(false)
    setShowTestModal(false)
    setSelectedTestType(null)
    setIsConnecting(false)
    setIsConnected(false)
  }

  const handleTestTypeSelection = (type: 'test_agent' | 'voice_ai_agent') => {
    setSelectedTestType(type)
    if (type === 'voice_ai_agent') {
      setShowModal(true)
      setShowTestModal(false)
    } else {
      setShowTestModal(false)
    }
  }


  const handleViewTestResult = (resultId: string) => {
    navigate(`/playground/test-agent-results/${resultId}`)
  }

  const toggleTestResultSelection = (resultId: string) => {
    setSelectedTestResultIds(prev => {
      const next = new Set(prev)
      if (next.has(resultId)) {
        next.delete(resultId)
      } else {
        next.add(resultId)
      }
      return next
    })
  }

  const toggleSelectAllTestResults = () => {
    const allIds = testVoiceAgentResults.map((r: any) => r.id)
    const allSelected = allIds.length > 0 && allIds.every((id: string) => selectedTestResultIds.has(id))
    setSelectedTestResultIds(allSelected ? new Set() : new Set(allIds))
  }

  const handleDeleteSelectedTestResults = async () => {
    if (selectedTestResultIds.size === 0) return
    if (!window.confirm(`Delete ${selectedTestResultIds.size} test result${selectedTestResultIds.size > 1 ? 's' : ''}? This cannot be undone.`)) return

    setIsDeletingSelectedTests(true)
    const ids = Array.from(selectedTestResultIds)
    try {
      const results = await Promise.allSettled(ids.map(id => apiClient.deleteEvaluatorResult(id)))
      const successCount = results.filter(r => r.status === 'fulfilled').length
      const failCount = results.filter(r => r.status === 'rejected').length

      if (successCount > 0) {
        queryClient.invalidateQueries({ queryKey: ['test-voice-agent-results'] })
        showToast(`Deleted ${successCount} test result${successCount > 1 ? 's' : ''}`, 'success')
      }
      if (failCount > 0) {
        showToast(`Failed to delete ${failCount} result${failCount > 1 ? 's' : ''}`, 'error')
      }

      setSelectedTestResultIds(prev => {
        const next = new Set(prev)
        ids.filter((_, i) => results[i].status === 'fulfilled').forEach(id => next.delete(id))
        return next
      })
    } finally {
      setIsDeletingSelectedTests(false)
    }
  }


  const handleOpenTestAgentTrace = (resultId: string) => {
    prefetchEvaluatorRecordingAudio(resultId)
    void queryClient.prefetchQuery({
      queryKey: ['evaluator-result', resultId],
      queryFn: () => apiClient.getEvaluatorResult(resultId, true),
      staleTime: 30_000,
    })
    setOtlpTraceResultId(resultId)
  }

  const handleViewCallRecording = (callShortId: string) => {
    navigate(`/playground/call-recordings/${callShortId}`)
  }

  const handleEvaluateCustomSession = async (callShortId: string) => {
    try {
      await apiClient.evaluateCustomWebsocketSession(callShortId)
      showToast('Evaluation queued for custom websocket session', 'success')
      queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
      queryClient.invalidateQueries({ queryKey: ['test-voice-agent-results'] })
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || 'Failed to queue evaluation'
      showToast(detail, 'error')
    }
  }

  const voiceAICallRecordings = callRecordings.filter(isVoiceAiProviderRecording)
  const customWebsocketSessions = callRecordings.filter((recording: any) => recording.provider_platform === 'custom_websocket')

  useEffect(() => {
    setListSearchQuery('')
    setListStatusFilter('all')
    setTestAgentsPage(1)
    setVoiceAiPage(1)
    setCustomWsPage(1)
  }, [activeTab])

  useEffect(() => {
    setTestAgentsPage(1)
    setVoiceAiPage(1)
    setCustomWsPage(1)
  }, [listSearchQuery, listStatusFilter])

  const filteredTestResults = useMemo(() => {
    let rows = testVoiceAgentResults
    if (listStatusFilter !== 'all') {
      rows = rows.filter((result: { status?: string }) => result.status === listStatusFilter)
    }
    const query = listSearchQuery.trim().toLowerCase()
    if (!query) return rows
    return rows.filter((result) => {
      const callId = String(result.result_id || result.id || '').toLowerCase()
      const agentName = String(result.agent?.name || '').toLowerCase()
      return callId.includes(query) || agentName.includes(query)
    })
  }, [testVoiceAgentResults, listSearchQuery, listStatusFilter])

  const filteredVoiceAiCalls = useMemo(() => {
    let rows = voiceAICallRecordings
    if (listStatusFilter !== 'all') {
      rows = rows.filter((recording: { status?: string; evaluation_status?: string }) => {
        if (listStatusFilter === 'pending_eval') {
          return !recording.evaluation_status || recording.evaluation_status === 'pending'
        }
        return recording.evaluation_status === listStatusFilter || recording.status === listStatusFilter
      })
    }
    const query = listSearchQuery.trim().toLowerCase()
    if (!query) return rows
    return rows.filter((recording: { call_short_id?: string; provider_platform?: string }) => {
      const callId = String(recording.call_short_id || '').toLowerCase()
      const platform = String(recording.provider_platform || '').toLowerCase()
      return callId.includes(query) || platform.includes(query)
    })
  }, [voiceAICallRecordings, listSearchQuery, listStatusFilter])

  const filteredCustomWsSessions = useMemo(() => {
    let rows = customWebsocketSessions
    if (listStatusFilter !== 'all') {
      rows = rows.filter((session: any) => {
        if (listStatusFilter === 'pending_eval') {
          return !session.evaluator_result_id
        }
        return session.evaluation_status === listStatusFilter || session.status === listStatusFilter
      })
    }
    const query = listSearchQuery.trim().toLowerCase()
    if (!query) return rows
    return rows.filter((session: { call_short_id?: string }) =>
      String(session.call_short_id || '').toLowerCase().includes(query),
    )
  }, [customWebsocketSessions, listSearchQuery, listStatusFilter])

  const paginatedTestResults = useMemo(
    () => paginateList(filteredTestResults, testAgentsPage, PLAYGROUND_LIST_PAGE_SIZE),
    [filteredTestResults, testAgentsPage],
  )
  const paginatedVoiceAiCalls = useMemo(
    () => paginateList(filteredVoiceAiCalls, voiceAiPage, PLAYGROUND_LIST_PAGE_SIZE),
    [filteredVoiceAiCalls, voiceAiPage],
  )
  const paginatedCustomWsSessions = useMemo(
    () => paginateList(filteredCustomWsSessions, customWsPage, PLAYGROUND_LIST_PAGE_SIZE),
    [filteredCustomWsSessions, customWsPage],
  )

  useEffect(() => {
    if (paginatedTestResults.page !== testAgentsPage) {
      setTestAgentsPage(paginatedTestResults.page)
    }
  }, [paginatedTestResults.page, testAgentsPage])

  useEffect(() => {
    if (paginatedVoiceAiCalls.page !== voiceAiPage) {
      setVoiceAiPage(paginatedVoiceAiCalls.page)
    }
  }, [paginatedVoiceAiCalls.page, voiceAiPage])

  useEffect(() => {
    if (paginatedCustomWsSessions.page !== customWsPage) {
      setCustomWsPage(paginatedCustomWsSessions.page)
    }
  }, [paginatedCustomWsSessions.page, customWsPage])

  useEffect(() => {
    warmCallRecordingQueryFromList(queryClient, callRecordings)
  }, [callRecordings, queryClient])


  const toggleCallSelection = (callShortId: string) => {
    setSelectedCallIds(prev => {
      const next = new Set(prev)
      if (next.has(callShortId)) {
        next.delete(callShortId)
      } else {
        next.add(callShortId)
      }
      return next
    })
  }

  const toggleSelectAllCalls = () => {
    const allIds = voiceAICallRecordings.map((r: any) => r.call_short_id)
    const allSelected = allIds.length > 0 && allIds.every((id: string) => selectedCallIds.has(id))
    setSelectedCallIds(allSelected ? new Set() : new Set(allIds))
  }

  const handleDeleteSelectedCalls = async () => {
    if (selectedCallIds.size === 0) return
    if (!window.confirm(`Delete ${selectedCallIds.size} call recording${selectedCallIds.size > 1 ? 's' : ''}? This cannot be undone.`)) return

    setIsDeletingSelected(true)
    const ids = Array.from(selectedCallIds)
    try {
      const results = await Promise.allSettled(ids.map(id => apiClient.deleteCallRecording(id)))
      const successCount = results.filter(r => r.status === 'fulfilled').length
      const failCount = results.filter(r => r.status === 'rejected').length

      if (successCount > 0) {
        queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
        showToast(`Deleted ${successCount} recording${successCount > 1 ? 's' : ''}`, 'success')
      }
      if (failCount > 0) {
        showToast(`Failed to delete ${failCount} recording${failCount > 1 ? 's' : ''}`, 'error')
      }

      setSelectedCallIds(prev => {
        const next = new Set(prev)
        ids.filter((_, i) => results[i].status === 'fulfilled').forEach(id => next.delete(id))
        return next
      })
    } finally {
      setIsDeletingSelected(false)
    }
  }

  const handleRefreshStatus = async () => {
    setIsRefreshingStatus(true)
    try {
      await Promise.all([refetchTestResults(), refetchCallRecordings()])
      showToast('Latest evaluation status refreshed', 'success')
    } catch {
      showToast('Failed to refresh status', 'error')
    } finally {
      setIsRefreshingStatus(false)
    }
  }


  return (
    <>
      <ToastContainer />
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Agent Playground</h2>
            <p className="mt-1 text-sm text-gray-600">
              Test your voice AI agent with real-time web calls
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={handleRefreshStatus}
              leftIcon={<RefreshCw className="h-4 w-4" />}
              isLoading={isRefreshingStatus}
              disabled={!selectedAgent}
            >
              Refresh
            </Button>
            <Button
              variant="primary"
              onClick={() => setShowTestModal(true)}
              leftIcon={<Play className="h-5 w-5" />}
              disabled={!selectedAgent || (!hasTestAgent && !hasVoiceAIAgent)}
            >
              Test
            </Button>
          </div>
        </div>

        <div className="p-6">
          {!selectedAgent ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-sm text-yellow-800">
                Please select an agent from the top bar to use the Agent Playground.
              </p>
            </div>
          ) : !hasTestAgent && !hasVoiceAIAgent ? (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm text-blue-800">
                <strong>Selected Agent:</strong> {selectedAgent.name}
              </p>
              <p className="text-sm text-blue-700 mt-2">
                {!hasVoiceAIIntegration && 'Link a Voice AI integration (Retell, Vapi, ElevenLabs, or Smallest) and set the Agent ID. '}
                {!hasTestAgent && 'Attach a Voice Bundle for Test Agent mode. '}
                Please check your agent configuration.
              </p>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <p className="text-sm text-green-800">
                <strong>Ready to test:</strong> {selectedAgent.name}
              </p>
              <p className="text-sm text-green-700 mt-1">
                Click the Play button to start a web call with your Voice Agent.
              </p>
            </div>
          )}

          {/* Tabs Section */}
          <div className="mt-6">
            <div className="border-b border-gray-200">
              <nav className="-mb-px flex space-x-8" aria-label="Tabs">
                <button
                  onClick={() => setActiveTab('voice_ai_agents')}
                  className={`
                    flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm
                    ${
                      activeTab === 'voice_ai_agents'
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }
                  `}
                >
                  <PhoneCall className="h-4 w-4" />
                  Voice AI Agents
                </button>
                <button
                  onClick={() => setActiveTab('test_agents')}
                  className={`
                    flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm
                    ${
                      activeTab === 'test_agents'
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }
                  `}
                >
                  <Bot className="h-4 w-4" />
                  Test Agents
                </button>
                <button
                  onClick={() => setActiveTab('custom_websocket')}
                  className={`
                    flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm
                    ${
                      activeTab === 'custom_websocket'
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }
                  `}
                >
                  <Mic className="h-4 w-4" />
                  Custom WebSocket Testing
                </button>
              </nav>
            </div>
            {/* Test Agents Tab Content */}
            {activeTab === 'test_agents' && (
              <div className="mt-4">
                {selectedTestResultIds.size > 0 && (
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm text-gray-600">{selectedTestResultIds.size} selected</span>
                    <Button
                      variant="danger"
                      onClick={handleDeleteSelectedTestResults}
                      disabled={isDeletingSelectedTests}
                      isLoading={isDeletingSelectedTests}
                      leftIcon={!isDeletingSelectedTests ? <Trash2 className="h-4 w-4" /> : undefined}
                    >
                      Delete ({selectedTestResultIds.size})
                    </Button>
                  </div>
                )}
                {testVoiceAgentResults.length === 0 ? (
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
                    <p className="text-sm text-gray-600">No test agent results found</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <PlaygroundListToolbar
                      search={listSearchQuery}
                      onSearchChange={setListSearchQuery}
                      statusFilter={listStatusFilter}
                      onStatusChange={setListStatusFilter}
                      statusOptions={[
                        { value: 'all', label: 'Any status' },
                        { value: 'completed', label: 'Completed' },
                        { value: 'failed', label: 'Failed' },
                        { value: 'in_progress', label: 'In progress' },
                      ]}
                    />
                    {filteredTestResults.length === 0 ? (
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-600">
                        No calls match your search.{' '}
                        <button
                          type="button"
                          onClick={() => {
                            setListSearchQuery('')
                            setListStatusFilter('all')
                          }}
                          className="font-medium text-primary-600 hover:text-primary-800"
                        >
                          Clear filters
                        </button>
                      </div>
                    ) : (
                      <>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
                            <button
                              type="button"
                              onClick={toggleSelectAllTestResults}
                              className="flex-shrink-0"
                              aria-label="Select all test results"
                            >
                              {testVoiceAgentResults.length > 0 && testVoiceAgentResults.every((r: any) => selectedTestResultIds.has(r.id)) ? (
                                <CheckSquare className="w-5 h-5 text-primary-600" />
                              ) : (
                                <Square className="w-5 h-5 text-gray-400" />
                              )}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Call ID
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Agent
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Created
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                            Trace
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {paginatedTestResults.items.map((result: any) => {
                          const isSelected = selectedTestResultIds.has(result.id)
                          return (
                            <tr
                              key={result.id}
                              className={`hover:bg-gray-50 cursor-pointer transition-colors ${isSelected ? 'bg-blue-50' : ''}`}
                              onClick={() => handleViewTestResult(result.id)}
                              onMouseEnter={() => {
                                prefetchEvaluatorRecordingAudio(result.id)
                                void queryClient.prefetchQuery({
                                  queryKey: ['evaluator-result', result.id],
                                  queryFn: () => apiClient.getEvaluatorResult(result.id, true),
                                  staleTime: 30_000,
                                })
                              }}
                            >
                              <td className="px-6 py-5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                                <button
                                  type="button"
                                  onClick={() => toggleTestResultSelection(result.id)}
                                  className="flex-shrink-0"
                                >
                                  {isSelected ? (
                                    <CheckSquare className="w-5 h-5 text-primary-600" />
                                  ) : (
                                    <Square className="w-5 h-5 text-gray-400" />
                                  )}
                                </button>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap">
                                <span className="font-mono text-sm font-semibold text-primary-600">
                                  {result.result_id || result.id.substring(0, 8)}
                                </span>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap">
                                <span
                                  className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                                    result.status === 'completed'
                                      ? 'bg-green-100 text-green-800'
                                      : result.status === 'failed'
                                      ? 'bg-red-100 text-red-800'
                                      : 'bg-yellow-100 text-yellow-800'
                                  }`}
                                >
                                  {result.status}
                                </span>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap text-sm text-gray-500">
                                {result.agent?.name || 'N/A'}
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap text-sm text-gray-500">
                                {result.created_at
                                  ? new Date(result.created_at).toLocaleString()
                                  : 'N/A'}
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                                <button
                                  type="button"
                                  onClick={() => handleOpenTestAgentTrace(result.id)}
                                  className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                                  title="View OTLP call trace"
                                >
                                  <Activity className="h-3.5 w-3.5" />
                                  Trace
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                    <TableListPagination
                      page={paginatedTestResults.page}
                      pageCount={paginatedTestResults.pageCount}
                      total={paginatedTestResults.total}
                      pageSize={PLAYGROUND_LIST_PAGE_SIZE}
                      onPrev={() => setTestAgentsPage((page) => Math.max(1, page - 1))}
                      onNext={() =>
                        setTestAgentsPage((page) => Math.min(paginatedTestResults.pageCount, page + 1))
                      }
                    />
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Voice AI Agents Tab Content */}
            {activeTab === 'voice_ai_agents' && (
              <div className="mt-4">
                {selectedCallIds.size > 0 && (
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm text-gray-600">{selectedCallIds.size} selected</span>
                    <Button
                      variant="danger"
                      onClick={handleDeleteSelectedCalls}
                      disabled={isDeletingSelected}
                      isLoading={isDeletingSelected}
                      leftIcon={!isDeletingSelected ? <Trash2 className="h-4 w-4" /> : undefined}
                    >
                      Delete ({selectedCallIds.size})
                    </Button>
                  </div>
                )}
                {voiceAICallRecordings.length === 0 ? (
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
                    <p className="text-sm text-gray-600">
                      No Retell, Vapi, ElevenLabs, or Smallest calls yet. Start a Voice AI Agent test from the agent sidebar.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <PlaygroundListToolbar
                      search={listSearchQuery}
                      onSearchChange={setListSearchQuery}
                      statusFilter={listStatusFilter}
                      onStatusChange={setListStatusFilter}
                      statusOptions={[
                        { value: 'all', label: 'Any status' },
                        { value: 'completed', label: 'Evaluated' },
                        { value: 'evaluating', label: 'Evaluating' },
                        { value: 'failed', label: 'Failed' },
                        { value: 'pending_eval', label: 'Pending eval' },
                      ]}
                    />
                    {filteredVoiceAiCalls.length === 0 ? (
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-600">
                        No calls match your search.{' '}
                        <button
                          type="button"
                          onClick={() => {
                            setListSearchQuery('')
                            setListStatusFilter('all')
                          }}
                          className="font-medium text-primary-600 hover:text-primary-800"
                        >
                          Clear filters
                        </button>
                      </div>
                    ) : (
                      <>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
                            <button
                              type="button"
                              onClick={toggleSelectAllCalls}
                              className="flex-shrink-0"
                              aria-label="Select all call recordings"
                            >
                              {voiceAICallRecordings.length > 0 && voiceAICallRecordings.every((r: any) => selectedCallIds.has(r.call_short_id)) ? (
                                <CheckSquare className="w-5 h-5 text-primary-600" />
                              ) : (
                                <Square className="w-5 h-5 text-gray-400" />
                              )}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Call ID
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Evaluation
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Platform
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Created
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {paginatedVoiceAiCalls.items.map((recording: any) => {
                          const isSelected = selectedCallIds.has(recording.call_short_id)
                          return (
                            <tr
                              key={recording.id}
                              className={`hover:bg-gray-50 cursor-pointer transition-colors ${isSelected ? 'bg-blue-50' : ''}`}
                              onClick={() => handleViewCallRecording(recording.call_short_id)}
                              onMouseEnter={() => {
                                prefetchCallRecordingAudio(recording.call_short_id, false)
                                void prefetchCallRecordingQuery(queryClient, recording.call_short_id)
                              }}
                            >
                              <td className="px-6 py-5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                                <button
                                  type="button"
                                  onClick={() => toggleCallSelection(recording.call_short_id)}
                                  className="flex-shrink-0"
                                >
                                  {isSelected ? (
                                    <CheckSquare className="w-5 h-5 text-primary-600" />
                                  ) : (
                                    <Square className="w-5 h-5 text-gray-400" />
                                  )}
                                </button>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap">
                                <span className="font-mono text-sm font-semibold text-primary-600">
                                  {recording.call_short_id}
                                </span>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap">
                                <span
                                  className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${recording.status === 'UPDATED'
                                    ? 'bg-green-100 text-green-800'
                                    : 'bg-yellow-100 text-yellow-800'
                                    }`}
                                >
                                  {recording.status}
                                </span>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap">
                                {recording.evaluator_result_id ? (
                                  <span
                                    className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                                      recording.evaluation_status === 'completed'
                                        ? 'bg-green-100 text-green-800'
                                        : recording.evaluation_status === 'failed'
                                        ? 'bg-red-100 text-red-800'
                                        : recording.evaluation_status === 'evaluating'
                                        ? 'bg-blue-100 text-blue-800'
                                        : 'bg-yellow-100 text-yellow-800'
                                    }`}
                                  >
                                    {recording.evaluation_status || 'queued'}
                                  </span>
                                ) : recording.status === 'UPDATED' ? (
                                  <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-600">
                                    Pending
                                  </span>
                                ) : (
                                  <span className="text-xs text-gray-400">—</span>
                                )}
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap">
                                <div className="flex items-center gap-2">
                                  {recording.provider_platform ? (() => {
                                    const logo = getIntegrationPlatformLogo(
                                      recording.provider_platform as IntegrationPlatform,
                                    )
                                    return logo ? (
                                      <img
                                        src={logo}
                                        alt={recording.provider_platform}
                                        className="h-5 w-5 object-contain"
                                      />
                                    ) : null
                                  })() : null}
                                  <span className="text-sm text-gray-500 capitalize">
                                    {recording.provider_platform || 'N/A'}
                                  </span>
                                </div>
                              </td>
                              <td className="px-6 py-5 whitespace-nowrap text-sm text-gray-500">
                                {recording.created_at
                                  ? new Date(recording.created_at).toLocaleString()
                                  : 'N/A'}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                    <TableListPagination
                      page={paginatedVoiceAiCalls.page}
                      pageCount={paginatedVoiceAiCalls.pageCount}
                      total={paginatedVoiceAiCalls.total}
                      pageSize={PLAYGROUND_LIST_PAGE_SIZE}
                      onPrev={() => setVoiceAiPage((page) => Math.max(1, page - 1))}
                      onNext={() =>
                        setVoiceAiPage((page) => Math.min(paginatedVoiceAiCalls.pageCount, page + 1))
                      }
                    />
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'custom_websocket' && (
              <div className="mt-4 space-y-4">
                <div className="rounded-lg border border-gray-200 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">Test a Custom WebSocket Voice Agent</h3>
                  <p className="mt-1 text-xs text-gray-600">
                    Paste or pick a saved WebSocket endpoint and start a live call. After disconnect you can save the transcript and evaluate.
                  </p>

                  {/* URL input + save button */}
                  <div className="mt-3 flex gap-2">
                    <input
                      value={customWebsocketUrl}
                      onChange={(e) => setCustomWebsocketUrl(e.target.value)}
                      placeholder="wss://your-voice-agent.example.com/ws"
                      className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-200"
                    />
                    {customWebsocketUrl.trim() && (
                      isCurrentUrlSaved ? (
                        <button
                          className="flex items-center gap-1 px-3 py-2 rounded-lg text-xs font-medium text-primary-600 bg-primary-50 border border-primary-200"
                          title="Already saved"
                          disabled
                        >
                          <BookmarkCheck className="h-4 w-4" />
                          Saved
                        </button>
                      ) : (
                        <button
                          className="flex items-center gap-1 px-3 py-2 rounded-lg text-xs font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 transition-colors"
                          onClick={() => setShowSaveForm((v) => !v)}
                          title="Save this URL for later"
                        >
                          <Bookmark className="h-4 w-4" />
                          Save
                        </button>
                      )
                    )}
                  </div>

                  {/* Inline save form */}
                  {showSaveForm && (
                    <div className="mt-2 flex gap-2 items-center">
                      <input
                        value={saveLabel}
                        onChange={(e) => setSaveLabel(e.target.value)}
                        placeholder="Label (e.g. My Voice Bot)"
                        className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-200"
                        onKeyDown={(e) => { if (e.key === 'Enter') handleSaveUrl() }}
                        autoFocus
                      />
                      <Button size="sm" onClick={handleSaveUrl}>Save</Button>
                      <button className="text-gray-400 hover:text-gray-600" onClick={() => setShowSaveForm(false)}>
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  )}

                  {/* Saved URLs list */}
                  {savedWsUrls.length > 0 && (
                    <div className="mt-3">
                      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mb-1.5">Saved Endpoints</p>
                      <div className="flex flex-wrap gap-2">
                        {savedWsUrls.map((s) => (
                          <button
                            key={s.id}
                            className={`group flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-colors ${
                              customWebsocketUrl.trim() === s.url
                                ? 'border-primary-400 bg-primary-50 text-primary-700 font-medium'
                                : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50 hover:border-gray-300'
                            }`}
                            onClick={() => setCustomWebsocketUrl(s.url)}
                            title={s.url}
                          >
                            <Bookmark className="h-3 w-3 flex-shrink-0" />
                            <span className="truncate max-w-[200px]">{s.label}</span>
                            <span
                              className="hidden group-hover:inline-flex ml-1 text-gray-400 hover:text-red-500"
                              onClick={(e) => { e.stopPropagation(); handleDeleteSavedUrl(s.id) }}
                              title="Remove"
                            >
                              <X className="h-3 w-3" />
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {customWebsocketUrl.trim().startsWith('ws://') || customWebsocketUrl.trim().startsWith('wss://') ? (
                  <GenericVoiceWSClient
                    websocketUrl={customWebsocketUrl.trim()}
                    protocol={getProtocolById('generic')}
                    agentId={selectedAgent?.id}
                    onSessionSaved={() => {
                      queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
                      queryClient.invalidateQueries({ queryKey: ['test-voice-agent-results'] })
                    }}
                  />
                ) : (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                    Enter a valid WebSocket URL (<code className="bg-amber-100 px-1 rounded">ws://</code> or <code className="bg-amber-100 px-1 rounded">wss://</code>) to start testing.
                  </div>
                )}

                <div className="rounded-lg border border-gray-200">
                  <div className="border-b border-gray-200 px-4 py-3">
                    <h4 className="text-sm font-semibold text-gray-900">Saved Custom Sessions</h4>
                  </div>
                  <div className="p-4">
                    {customWebsocketSessions.length === 0 ? (
                      <p className="text-sm text-gray-600">No saved custom websocket sessions yet.</p>
                    ) : (
                      <div className="space-y-3">
                        <PlaygroundListToolbar
                          search={listSearchQuery}
                          onSearchChange={setListSearchQuery}
                          statusFilter={listStatusFilter}
                          onStatusChange={setListStatusFilter}
                          statusOptions={[
                            { value: 'all', label: 'Any status' },
                            { value: 'UPDATED', label: 'Updated' },
                            { value: 'completed', label: 'Evaluated' },
                            { value: 'pending_eval', label: 'Pending eval' },
                          ]}
                        />
                        {filteredCustomWsSessions.length === 0 ? (
                          <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-600">
                            No calls match your search.{' '}
                            <button
                              type="button"
                              onClick={() => {
                                setListSearchQuery('')
                                setListStatusFilter('all')
                              }}
                              className="font-medium text-primary-600 hover:text-primary-800"
                            >
                              Clear filters
                            </button>
                          </div>
                        ) : (
                          <>
                      <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Call ID</th>
                              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Evaluation</th>
                              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-200 bg-white">
                            {paginatedCustomWsSessions.items.map((session: any) => (
                              <tr
                                key={session.id}
                                className="hover:bg-gray-50 cursor-pointer transition-colors"
                                onClick={() => handleViewCallRecording(session.call_short_id)}
                              >
                                <td className="px-6 py-5 text-sm font-mono font-semibold text-primary-600">
                                  {session.call_short_id}
                                </td>
                                <td className="px-6 py-5 text-sm text-gray-600">{session.status}</td>
                                <td className="px-6 py-5">
                                  {session.evaluator_result_id ? (
                                    <span className="inline-flex rounded-full bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-800">
                                      {session.evaluation_status || 'queued'}
                                    </span>
                                  ) : (
                                    <span className="inline-flex rounded-full bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-700">
                                      pending
                                    </span>
                                  )}
                                </td>
                                <td className="px-6 py-5 text-sm text-gray-600">
                                  {session.created_at ? new Date(session.created_at).toLocaleString() : 'N/A'}
                                </td>
                                <td className="px-6 py-4" onClick={(e) => e.stopPropagation()}>
                                  <div className="flex flex-wrap gap-2">
                                    {!session.evaluator_result_id && (
                                      <Button
                                        variant="outline"
                                        onClick={() => handleEvaluateCustomSession(session.call_short_id)}
                                      >
                                        Run Evaluation
                                      </Button>
                                    )}
                                    {session.evaluator_result_id && (
                                      <Button
                                        variant="outline"
                                        onClick={() => handleViewTestResult(session.evaluator_result_id)}
                                      >
                                        Open Result
                                      </Button>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                        <TableListPagination
                          page={paginatedCustomWsSessions.page}
                          pageCount={paginatedCustomWsSessions.pageCount}
                          total={paginatedCustomWsSessions.total}
                          pageSize={PLAYGROUND_LIST_PAGE_SIZE}
                          onPrev={() => setCustomWsPage((page) => Math.max(1, page - 1))}
                          onNext={() =>
                            setCustomWsPage((page) => Math.min(paginatedCustomWsSessions.pageCount, page + 1))
                          }
                        />
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>


      {/* Test Type Selection Modal */}
      {showTestModal && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Select Test Type</h3>
              <button
                onClick={handleCloseModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6">
              <div className="text-center mb-4">
                <p className="text-sm text-gray-600 mb-2">
                  Agent: <strong>{selectedAgent?.name}</strong>
                </p>
                <p className="text-xs text-gray-500">
                  Choose how you want to test this agent
                </p>
              </div>

              {s3Status && !s3Status.enabled && (
                <div className="flex items-start gap-3 p-3 bg-amber-50 border border-amber-200 rounded-lg mb-3">
                  <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-amber-800">Storage not configured</p>
                    <p className="text-xs text-amber-700 mt-0.5">
                      S3 storage is not configured. Audio recordings will not be saved. Configure storage in Settings &gt; Data Sources to enable audio playback.
                    </p>
                  </div>
                </div>
              )}

              <div className="flex items-start gap-2.5 p-3 bg-blue-50 border border-blue-200 rounded-lg mb-1">
                <AlertTriangle className="h-4 w-4 text-blue-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-blue-700">
                  First-time runs may take longer as ML models required for audio evaluation metrics are downloaded and cached locally. Subsequent runs will be significantly faster.
                </p>
              </div>

              <div className="space-y-3">
                {hasTestAgent && (
                  <button
                    onClick={() => handleTestTypeSelection('test_agent')}
                    className="w-full p-4 border-2 border-gray-200 rounded-lg hover:border-blue-500 hover:bg-blue-50 transition-all text-left"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-blue-100 rounded-lg">
                        <Mic className="h-5 w-5 text-blue-600" />
                      </div>
                      <div>
                        <h4 className="font-semibold text-gray-900">Test Agent</h4>
                        <p className="text-sm text-gray-600">Test with Voice Bundle (STT/TTS/LLM)</p>
                      </div>
                    </div>
                  </button>
                )}

                {hasVoiceAIAgent && (
                  <button
                    onClick={() => handleTestTypeSelection('voice_ai_agent')}
                    className="w-full p-4 border-2 border-gray-200 rounded-lg hover:border-blue-500 hover:bg-blue-50 transition-all text-left"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-green-100 rounded-lg">
                        <Phone className="h-5 w-5 text-green-600" />
                      </div>
                      <div>
                        <h4 className="font-semibold text-gray-900">Voice AI Agent</h4>
                        <p className="text-sm text-gray-600">Test with Voice AI Integration (Retell, Vapi, ElevenLabs, Smallest)</p>
                      </div>
                    </div>
                  </button>
                )}

                {!hasTestAgent && !hasVoiceAIAgent && (
                  <div className="text-center py-4">
                    <p className="text-sm text-gray-600 mb-4">
                      This agent is not configured for testing.
                    </p>
                    <Button
                      variant="outline"
                      onClick={handleCloseModal}
                    >
                      Close
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Voice AI Agent Connect Modal (Retell) */}
      {showModal && selectedTestType === 'voice_ai_agent' && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Connect to Voice AI Agent</h3>
              <button
                onClick={handleCloseModal}
                className="text-gray-400 hover:text-gray-600"
                disabled={isConnecting}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6">
              {!canMakeCall ? (
                <div className="text-center py-4">
                  <p className="text-sm text-gray-600 mb-4">
                    This agent is not configured for web calls.
                  </p>
                  <Button
                    variant="outline"
                    onClick={handleCloseModal}
                  >
                    Close
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="text-center">
                    <p className="text-sm text-gray-600 mb-2">
                      Agent: <strong>{selectedAgent?.name}</strong>
                    </p>
                    <p className="text-xs text-gray-500">
                      Provider: {agentIntegration?.platform || 'Unknown'}
                    </p>
                    <p className="text-xs text-gray-500">
                      Agent ID: <span className="font-mono font-semibold text-primary-600">{fullAgent?.voice_ai_agent_id}</span>
                    </p>
                  </div>

                  {isConnected && (
                    <div className="h-48 overflow-y-auto bg-gray-50 rounded p-4 mb-4 space-y-3 border border-gray-200">
                      {transcripts.length === 0 ? (
                        <p className="text-gray-400 text-xs text-center italic">Waiting for connection...</p>
                      ) : (
                        transcripts.map((msg, idx) => (
                          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${msg.role === 'user'
                              ? 'bg-indigo-600 text-white rounded-br-none'
                              : 'bg-white border border-gray-200 text-gray-800 rounded-bl-none'
                              }`}>
                              <p className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${
                                msg.role === 'user' ? 'opacity-70' : 'text-gray-400'
                              }`}>
                                {msg.role === 'user' ? 'You' : 'Agent'}
                              </p>
                              <p className="text-sm leading-relaxed">{msg.content}</p>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  )}

                  {!isConnected ? (
                    <Button
                      variant="primary"
                      onClick={handleConnect}
                      isLoading={isConnecting}
                      leftIcon={!isConnecting ? <Phone className="h-5 w-5" /> : undefined}
                      className="w-full"
                      disabled={isConnecting}
                    >
                      {isConnecting ? 'Connecting...' : 'Connect'}
                    </Button>
                  ) : (
                    <div className="space-y-3">
                      <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-center">
                        <p className="text-sm text-green-800 font-medium">Connected</p>
                        <p className="text-xs text-green-700 mt-1">Call is active</p>
                      </div>
                      <Button
                        variant="danger"
                        onClick={handleDisconnect}
                        leftIcon={<PhoneOff className="h-5 w-5" />}
                        className="w-full"
                      >
                        Disconnect
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Test Agent Modal */}
      {selectedTestType === 'test_agent' && !showTestModal && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <div>
                <h3 className="text-lg font-semibold">Test Agent — {selectedAgent?.name}</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  You play the production agent. The simulated caller uses your voice bundle + persona + scenario.
                </p>
              </div>
              <button
                onClick={handleCloseModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="test-persona" className="block text-sm font-medium text-gray-700 mb-1">
                    Persona
                  </label>
                  <select
                    id="test-persona"
                    value={testPersonaId}
                    onChange={(e) => setTestPersonaId(e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-blue-500"
                  >
                    <option value="">Select persona…</option>
                    {eligibleTestPersonas.map((persona: any) => (
                      <option key={persona.id} value={persona.id}>
                        {persona.name}
                        {persona.tts_voice_name ? ` · ${persona.tts_voice_name}` : ''}
                      </option>
                    ))}
                  </select>
                  {testVoiceBundleTtsProvider && eligibleTestPersonas.length === 0 && (
                    <p className="text-xs text-amber-700 mt-1">
                      No personas match this agent&apos;s TTS provider ({testVoiceBundleTtsProvider}).
                      Create one under Personas with a matching voice.
                    </p>
                  )}
                  {selectedTestPersona && (
                    <p className="text-xs text-gray-500 mt-1">
                      Voice: {selectedTestPersona.tts_voice_name || selectedTestPersona.tts_voice_id || 'default'}
                    </p>
                  )}
                </div>

                <div>
                  <label htmlFor="test-scenario" className="block text-sm font-medium text-gray-700 mb-1">
                    Scenario
                  </label>
                  <select
                    id="test-scenario"
                    value={testScenarioId}
                    onChange={(e) => setTestScenarioId(e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-blue-500"
                  >
                    <option value="">Select scenario…</option>
                    {testScenarios.map((scenario: any) => (
                      <option key={scenario.id} value={scenario.id}>
                        {scenario.name}
                      </option>
                    ))}
                  </select>
                  {testScenarios.length === 0 && (
                    <p className="text-xs text-amber-700 mt-1">
                      No scenarios linked to this agent. Generate scenarios from the agent workspace first.
                    </p>
                  )}
                  {selectedTestScenario?.description && (
                    <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                      {selectedTestScenario.description}
                    </p>
                  )}
                </div>
              </div>

              <div className="flex items-start justify-between gap-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-900">Run post-call evaluation</p>
                  <p className="text-xs text-gray-600 mt-0.5">
                    Off by default. Enable to score this call automatically when it ends, or run evaluation later from the results table.
                  </p>
                </div>
                <label className="relative inline-flex shrink-0 cursor-pointer items-center">
                  <input
                    type="checkbox"
                    className="peer sr-only"
                    checked={runPostCallEvaluation}
                    onChange={(e) => setRunPostCallEvaluation(e.target.checked)}
                  />
                  <span className="h-6 w-11 rounded-full bg-gray-300 transition peer-checked:bg-blue-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300" />
                  <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition peer-checked:translate-x-5" />
                </label>
              </div>

              {testSetupComplete && (
                <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
                  <p className="font-medium mb-1">Ready to simulate</p>
                  <p className="text-xs text-blue-800">
                    Caller: <strong>{selectedTestPersona?.name}</strong> · Scenario:{' '}
                    <strong>{selectedTestScenario?.name}</strong> · Agent template + production prompt drive the caller LLM.
                  </p>
                </div>
              )}

              {!testSetupComplete && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                  Select a persona and scenario to build the test agent system prompt before starting the call.
                </div>
              )}

              <VoiceAgent
                agentId={selectedAgent?.id}
                personaId={testPersonaId || undefined}
                scenarioId={testScenarioId || undefined}
                billingSurface="agent_playground"
                runEvaluation={runPostCallEvaluation}
                compact
                sidebarLayout
                connectDisabled={!testSetupComplete}
                connectDisabledReason="Select a persona and scenario first"
                userTranscriptLabel="You (production)"
                botTranscriptLabel="Test caller"
                onSessionSaved={() => {
                  queryClient.invalidateQueries({ queryKey: ['test-voice-agent-results'] })
                  refetchTestResults()
                }}
              />
            </div>
          </div>
        </div>
      )}

      <TraceDetailDrawer
        open={Boolean(otlpTraceResultId)}
        evaluatorResultId={otlpTraceResultId}
        onClose={() => setOtlpTraceResultId(null)}
      />
    </>
  )
}

