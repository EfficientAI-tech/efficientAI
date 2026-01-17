import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAgentStore } from '../store/agentStore'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { Play, X, Phone, PhoneOff, RefreshCw, Eye, Mic, Bot, PhoneCall, Trash2 } from 'lucide-react'
import Button from './Button'
import { useToast } from '../hooks/useToast'
import { RetellWebClient } from 'retell-client-js-sdk'
import Vapi from '@vapi-ai/web'
import VoiceAgent from './VoiceAgent'

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

export default function Playground() {
  const { selectedAgent } = useAgentStore()
  const { showToast, ToastContainer } = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [showTestModal, setShowTestModal] = useState(false)
  const [selectedTestType, setSelectedTestType] = useState<'test_agent' | 'voice_ai_agent' | null>(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [transcripts, setTranscripts] = useState<Array<{ role: 'user' | 'agent', content: string }>>([])

  const retellClientRef = useRef<RetellWebClientWithMethods | null>(null)
  const vapiClientRef = useRef<any>(null)
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


  // Fetch test voice agent evaluation results (playground results only)
  const { data: testVoiceAgentResults = [], refetch: refetchTestResults } = useQuery({
    queryKey: ['test-voice-agent-results'],
    queryFn: async () => {
      // Fetch only playground results (evaluator_id is NULL) - includes agent with voice bundle
      return await apiClient.listEvaluatorResults(undefined, true)
    },
  })

  // Fetch call recordings (for Voice AI Agents tab)
  const { data: callRecordings = [], refetch: refetchCallRecordings } = useQuery({
    queryKey: ['call-recordings'],
    queryFn: () => apiClient.listCallRecordings(),
  })

  const [activeTab, setActiveTab] = useState<'test_agents' | 'voice_ai_agents'>('test_agents')


  // Find the integration for the agent
  const agentIntegration = fullAgent?.voice_ai_integration_id
    ? integrations.find((int: any) => int.id === fullAgent.voice_ai_integration_id)
    : null

  const isRetellAgent = agentIntegration?.platform === 'retell'
  const isVapiAgent = agentIntegration?.platform === 'vapi'
  const hasWebCallEnabled = fullAgent?.call_medium === 'web_call'

  const canMakeCall = (isRetellAgent || isVapiAgent) && hasWebCallEnabled && fullAgent?.voice_ai_agent_id

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
        // Initialize Vapi with Public Key
        const client = new Vapi(agentIntegration.public_key)
        console.log('Vapi client initialized')
        vapiClientRef.current = client
      }
    }

    return () => {
      // Cleanup on unmount
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
    }
  }, [showModal, canMakeCall, isConnected, isRetellAgent, isVapiAgent, agentIntegration])

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
            setTranscripts(prev => {
              // Simple logic: if same role, update content (streaming), else new message
              // Retell sends incremental updates, so we might need to handle partials better
              // For now, let's just append finished sentences or major updates
              if (update.transcript.length > 0) {
                const role = update.role === 'user' ? 'user' : 'agent'
                const content = update.transcript
                return [...prev, { role, content }]
              }
              return prev
            })
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
        showToast(`Failed to connect: ${error.message}`, 'error')
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
        showToast(`Failed to connect: ${error.message}`, 'error')
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
    }

    setIsConnected(false)
    showToast('Disconnected', 'success')
  }

  const handleCloseModal = () => {
    if (isConnected && retellClientRef.current) {
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

  // Delete mutation for test agent results
  const deleteTestResultMutation = useMutation({
    mutationFn: (resultId: string) => apiClient.deleteEvaluatorResult(resultId),
    onSuccess: () => {
      showToast('Test result deleted successfully', 'success')
      queryClient.invalidateQueries({ queryKey: ['test-voice-agent-results'] })
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || 'Failed to delete test result', 'error')
    },
  })

  const handleDeleteTestResult = async (resultId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (window.confirm('Are you sure you want to delete this test result? This action cannot be undone.')) {
      deleteTestResultMutation.mutate(resultId)
    }
  }

  // Delete mutation for call recordings
  const deleteMutation = useMutation({
    mutationFn: (callShortId: string) => apiClient.deleteCallRecording(callShortId),
    onSuccess: () => {
      showToast('Call recording deleted successfully', 'success')
      queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || 'Failed to delete call recording', 'error')
    },
  })

  const handleViewCallRecording = (callShortId: string) => {
    navigate(`/playground/call-recordings/${callShortId}`)
  }

  const handleRefreshCallRecording = async (callShortId: string) => {
    try {
      await apiClient.refreshCallRecording(callShortId)
      refetchCallRecordings()
      showToast('Call recording refreshed', 'success')
    } catch (error: any) {
      showToast(error?.response?.data?.detail || 'Failed to refresh call recording', 'error')
    }
  }

  const handleDeleteCallRecording = (callShortId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (window.confirm('Are you sure you want to delete this call recording? This action cannot be undone.')) {
      deleteMutation.mutate(callShortId)
    }
  }


  return (
    <>
      <ToastContainer />
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Playground</h2>
            <p className="mt-1 text-sm text-gray-600">
              Test your voice AI agent with real-time web calls
            </p>
          </div>
          <div className="flex gap-2">
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
                Please select an agent from the top bar to use the playground.
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
              </nav>
            </div>
            {/* Test Agents Tab Content */}
            {activeTab === 'test_agents' && (
              <div className="mt-4">
                {testVoiceAgentResults.length === 0 ? (
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
                    <p className="text-sm text-gray-600">No test agent results found</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Test ID
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
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {testVoiceAgentResults.map((result: any) => (
                          <tr key={result.id} className="hover:bg-gray-50">
                            <td className="px-4 py-3 whitespace-nowrap">
                              <button
                                onClick={() => handleViewTestResult(result.id)}
                                className="font-mono text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline"
                              >
                                {result.id.substring(0, 8)}...
                              </button>
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
                            <td className="px-4 py-3 whitespace-nowrap text-sm font-medium">
                              <div className="flex items-center gap-2">
                                <button
                                  onClick={() => handleViewTestResult(result.id)}
                                  className="text-blue-600 hover:text-blue-900"
                                >
                                  <Eye className="h-4 w-4" />
                                </button>
                                <button
                                  onClick={() => refetchTestResults()}
                                  className="text-gray-600 hover:text-gray-900"
                                  title="Refresh"
                                >
                                  <RefreshCw className="h-4 w-4" />
                                </button>
                                <button
                                  onClick={(e) => handleDeleteTestResult(result.id, e)}
                                  className="text-red-600 hover:text-red-900"
                                  title="Delete"
                                  disabled={deleteTestResultMutation.isPending}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Voice AI Agents Tab Content */}
            {activeTab === 'voice_ai_agents' && (
              <div className="mt-4">
                {callRecordings.length === 0 ? (
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
                    <p className="text-sm text-gray-600">No call recordings found</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Call ID
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Platform
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Provider Call ID
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Created
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {callRecordings.map((recording: any) => (
                          <tr key={recording.id} className="hover:bg-gray-50">
                            <td className="px-4 py-3 whitespace-nowrap">
                              <button
                                onClick={() => handleViewCallRecording(recording.call_short_id)}
                                className="font-mono text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline"
                              >
                                {recording.call_short_id}
                              </button>
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
                                <span className="text-sm text-gray-500 capitalize">
                                  {recording.provider_platform || 'N/A'}
                                </span>
                              </div>
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 font-mono text-xs">
                              {recording.provider_call_id || 'N/A'}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                              {recording.created_at
                                ? new Date(recording.created_at).toLocaleString()
                                : 'N/A'}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap text-sm font-medium">
                              <div className="flex items-center gap-2">
                                <button
                                  onClick={() => handleViewCallRecording(recording.call_short_id)}
                                  className="text-blue-600 hover:text-blue-900"
                                >
                                  <Eye className="h-4 w-4" />
                                </button>
                                {recording.status === 'PENDING' && (
                                  <button
                                    onClick={() => handleRefreshCallRecording(recording.call_short_id)}
                                    className="text-gray-600 hover:text-gray-900"
                                    title="Refresh"
                                  >
                                    <RefreshCw className="h-4 w-4" />
                                  </button>
                                )}
                                <button
                                  onClick={(e) => handleDeleteCallRecording(recording.call_short_id, e)}
                                  className="text-red-600 hover:text-red-900"
                                  title="Delete"
                                  disabled={deleteMutation.isPending}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
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
                      Agent ID: {fullAgent?.voice_ai_agent_id}
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

