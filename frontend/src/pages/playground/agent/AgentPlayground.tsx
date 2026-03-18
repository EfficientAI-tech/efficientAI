import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAgentStore } from '../../../store/agentStore'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { Play, X, Phone, PhoneOff, RefreshCw, Mic, Bot, PhoneCall, Trash2, AlertTriangle, CheckSquare, Square } from 'lucide-react'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'
import { RetellWebClient } from 'retell-client-js-sdk'
import Vapi from '@vapi-ai/web'
import { Conversation } from '@elevenlabs/client'
import VoiceAgent from '../../../components/VoiceAgent'

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
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [isRefreshingStatus, setIsRefreshingStatus] = useState(false)
  const [transcripts, setTranscripts] = useState<Array<{ role: 'user' | 'agent', content: string }>>([])

  const retellClientRef = useRef<RetellWebClientWithMethods | null>(null)
  const vapiClientRef = useRef<any>(null)
  const elevenLabsConversationRef = useRef<any>(null)
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
  const { data: testVoiceAgentResults = [], refetch: refetchTestResults } = useQuery({
    queryKey: ['test-voice-agent-results'],
    queryFn: async () => {
      // Fetch only playground results (evaluator_id is NULL) AND exclude Voice AI agent results (provider_platform is NULL)
      return await apiClient.listEvaluatorResults(undefined, true, true)
    },
  })

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

  const [activeTab, setActiveTab] = useState<'test_agents' | 'voice_ai_agents'>('voice_ai_agents')
  const [selectedCallIds, setSelectedCallIds] = useState<Set<string>>(new Set())
  const [isDeletingSelected, setIsDeletingSelected] = useState(false)
  const [selectedTestResultIds, setSelectedTestResultIds] = useState<Set<string>>(new Set())
  const [isDeletingSelectedTests, setIsDeletingSelectedTests] = useState(false)


  // Find the integration for the agent
  const agentIntegration = fullAgent?.voice_ai_integration_id
    ? integrations.find((int: any) => int.id === fullAgent.voice_ai_integration_id)
    : null

  const isRetellAgent = agentIntegration?.platform === 'retell'
  const isVapiAgent = agentIntegration?.platform === 'vapi'
  const isElevenLabsAgent = agentIntegration?.platform === 'elevenlabs'
  const hasWebCallEnabled = fullAgent?.call_medium === 'web_call'

  const canMakeCall = (isRetellAgent || isVapiAgent || isElevenLabsAgent) && hasWebCallEnabled && fullAgent?.voice_ai_agent_id

  // Check if agent has Test Agent capabilities (voice bundle with STT/TTS/LLM)
  const hasTestAgent = fullAgent?.voice_bundle_id != null
  // Check if agent has Voice AI Agent capabilities (Retell/Vapi integration)
  const hasVoiceAIAgent = canMakeCall

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
      if (retellClientRef.current && isConnected) {
        try {
          retellClientRef.current.stopCall()
        } catch (e) {
          console.error('Error stopping Retell call on cleanup:', e)
        }
      }
      if (vapiClientRef.current && isConnected) {
        try {
          vapiClientRef.current.stop()
        } catch (e) {
          console.error('Error stopping Vapi call on cleanup:', e)
        }
      }
      if (elevenLabsConversationRef.current && isConnected) {
        try {
          elevenLabsConversationRef.current.endSession()
        } catch (e) {
          console.error('Error ending ElevenLabs session on cleanup:', e)
        }
        elevenLabsConversationRef.current = null
      }
    }
  }, [showModal, canMakeCall, isConnected, isRetellAgent, isVapiAgent, isElevenLabsAgent, agentIntegration])

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
            apiClient.refreshCallRecording(currentCallShortIdRef.current)
              .then(() => refetchCallRecordings())
              .catch(err => console.error('Failed to refresh metrics', err))
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

            apiClient.refreshCallRecording(currentCallShortIdRef.current)
              .then(() => refetchCallRecordings())
              .catch(err => console.error('Failed to refresh metrics', err))
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
                apiClient.refreshCallRecording(callShortId)
                  .then(() => refetchCallRecordings())
                  .catch(err => console.error('Failed to refresh metrics', err))
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


  const handleViewCallRecording = (callShortId: string) => {
    navigate(`/playground/call-recordings/${callShortId}`)
  }


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
    const allIds = callRecordings.map((r: any) => r.call_short_id)
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
                {!hasWebCallEnabled && 'This agent does not have web calling enabled. '}
                {!canMakeCall && 'This agent is not correctly configured for web calls. '}
                {(!fullAgent?.voice_ai_agent_id) && 'Agent ID is missing. '}
                Please check your configuration.
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
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
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
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Call ID
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Agent
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Created
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {testVoiceAgentResults.map((result: any) => {
                          const isSelected = selectedTestResultIds.has(result.id)
                          return (
                            <tr
                              key={result.id}
                              className={`hover:bg-gray-50 cursor-pointer transition-colors ${isSelected ? 'bg-blue-50' : ''}`}
                              onClick={() => handleViewTestResult(result.id)}
                            >
                              <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
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
                              <td className="px-4 py-3 whitespace-nowrap">
                                <span className="font-mono text-sm font-semibold text-primary-600">
                                  {result.result_id || result.id.substring(0, 8)}
                                </span>
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap">
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
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                                {result.agent?.name || 'N/A'}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                                {result.created_at
                                  ? new Date(result.created_at).toLocaleString()
                                  : 'N/A'}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
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
                {callRecordings.length === 0 ? (
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
                    <p className="text-sm text-gray-600">No call recordings found</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
                            <button
                              type="button"
                              onClick={toggleSelectAllCalls}
                              className="flex-shrink-0"
                              aria-label="Select all call recordings"
                            >
                              {callRecordings.length > 0 && callRecordings.every((r: any) => selectedCallIds.has(r.call_short_id)) ? (
                                <CheckSquare className="w-5 h-5 text-primary-600" />
                              ) : (
                                <Square className="w-5 h-5 text-gray-400" />
                              )}
                            </button>
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Call ID
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Evaluation
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Platform
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Created
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {callRecordings.map((recording: any) => {
                          const isSelected = selectedCallIds.has(recording.call_short_id)
                          return (
                            <tr
                              key={recording.id}
                              className={`hover:bg-gray-50 cursor-pointer transition-colors ${isSelected ? 'bg-blue-50' : ''}`}
                              onClick={() => handleViewCallRecording(recording.call_short_id)}
                            >
                              <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
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
                              <td className="px-4 py-3 whitespace-nowrap">
                                <span className="font-mono text-sm font-semibold text-primary-600">
                                  {recording.call_short_id}
                                </span>
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap">
                                <span
                                  className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${recording.status === 'UPDATED'
                                    ? 'bg-green-100 text-green-800'
                                    : 'bg-yellow-100 text-yellow-800'
                                    }`}
                                >
                                  {recording.status}
                                </span>
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap">
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
                              <td className="px-4 py-3 whitespace-nowrap">
                                <div className="flex items-center gap-2">
                                  {recording.provider_platform === 'retell' && (
                                    <img
                                      src="/retellai.png"
                                      alt="Retell"
                                      className="h-5 w-5 object-contain"
                                    />
                                  )}
                                  {recording.provider_platform === 'vapi' && (
                                    <img
                                      src="/vapiai.jpg"
                                      alt="Vapi"
                                      className="h-5 w-5 object-contain"
                                    />
                                  )}
                                  {recording.provider_platform === 'elevenlabs' && (
                                    <img
                                      src="/elevenlabs.jpg"
                                      alt="ElevenLabs"
                                      className="h-5 w-5 rounded-full object-contain"
                                    />
                                  )}
                                  <span className="text-sm text-gray-500 capitalize">
                                    {recording.provider_platform || 'N/A'}
                                  </span>
                                </div>
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
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
                )}
              </div>
            )}
          </div>
        </div>
      </div>


      {/* Test Type Selection Modal */}
      {showTestModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
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
                        <p className="text-sm text-gray-600">Test with Voice AI Integration (Retell, etc.)</p>
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
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
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
                    <div className="h-48 overflow-y-auto bg-gray-50 rounded p-3 mb-4 space-y-2 border border-gray-200">
                      {transcripts.length === 0 ? (
                        <p className="text-gray-400 text-xs text-center italic">Waiting for connection...</p>
                      ) : (
                        transcripts.map((msg, idx) => (
                          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${msg.role === 'user'
                              ? 'bg-blue-100 text-blue-900'
                              : 'bg-white border border-gray-200 text-gray-800'
                              }`}>
                              <p className="text-xs font-semibold mb-0.5 opacity-70">
                                {msg.role === 'user' ? 'You' : 'Agent'}
                              </p>
                              {msg.content}
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
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Test Agent - {selectedAgent?.name}</h3>
              <button
                onClick={handleCloseModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6">
              <VoiceAgent agentId={selectedAgent?.id} />
            </div>
          </div>
        </div>
      )}
    </>
  )
}

