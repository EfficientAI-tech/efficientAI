import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAgentStore } from '../store/agentStore'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { Play, X, Phone, PhoneOff, RefreshCw, Eye, Trash2 } from 'lucide-react'
import Button from './Button'
import { useToast } from '../hooks/useToast'
import { RetellWebClient } from 'retell-client-js-sdk'

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
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const retellClientRef = useRef<RetellWebClientWithMethods | null>(null)
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

  // Fetch call recordings (always enabled)
  const { data: callRecordings = [], refetch: refetchCallRecordings } = useQuery({
    queryKey: ['call-recordings'],
    queryFn: () => apiClient.listCallRecordings(),
  })


  // Find the integration for the agent
  const agentIntegration = fullAgent?.voice_ai_integration_id
    ? integrations.find((int: any) => int.id === fullAgent.voice_ai_integration_id)
    : null

  const isRetellAgent = agentIntegration?.platform === 'retell'
  const hasWebCallEnabled = fullAgent?.call_medium === 'web_call'
  const canMakeCall = isRetellAgent && hasWebCallEnabled && fullAgent?.voice_ai_agent_id

  // Initialize Retell client when modal opens
  useEffect(() => {
    if (showModal && canMakeCall && !retellClientRef.current) {
      const client = new RetellWebClient() as unknown as RetellWebClientWithMethods
      // Debug: Log client structure
      console.log('RetellWebClient instance:', client)
      console.log('Available methods:', Object.getOwnPropertyNames(Object.getPrototypeOf(client)))
      retellClientRef.current = client
    }
    
      return () => {
        // Cleanup on unmount
        if (retellClientRef.current && isConnected) {
          try {
            retellClientRef.current.stopCall()
          } catch (e) {
            console.error('Error stopping call on cleanup:', e)
          }
        }
      }
  }, [showModal, canMakeCall, isConnected])

  const handleConnect = async () => {
    if (!canMakeCall || !fullAgent?.id) {
      showToast('Agent is not configured for Retell web calls', 'error')
      return
    }

    if (!retellClientRef.current) {
      retellClientRef.current = new RetellWebClient() as unknown as RetellWebClientWithMethods
    }

    const client = retellClientRef.current
    setIsConnecting(true)

    try {
      // IMPORTANT: Request microphone permission FIRST, before creating the web call
      // This ensures we can start the conversation immediately after getting call_id
      // Retell requires the user to join within 30 seconds of create_web_call
      // We'll just verify permission is available, but let the SDK handle the actual stream
      try {
        const testStream = await navigator.mediaDevices.getUserMedia({ audio: true })
        console.log('Microphone access granted')
        // Immediately stop the test stream - SDK will get its own
        testStream.getTracks().forEach(track => track.stop())
      } catch (micError: any) {
        console.error('Microphone permission denied:', micError)
        setIsConnecting(false)
        showToast('Microphone permission is required for voice calls', 'error')
        return
      }

      // Set up event handlers before creating the call
      client.on('call_started', () => {
        console.log('Call started')
        setIsConnected(true)
        setIsConnecting(false)
        showToast('Connected to Retell agent', 'success')
      })

      client.on('call_ended', (data?: any) => {
        console.log('Call ended', data)
        console.log('End reason:', data?.reason || 'No reason provided')
        console.log('End code:', data?.code || 'No code provided')
        setIsConnected(false)
        setIsConnecting(false)
        // Only show toast if it wasn't a user-initiated disconnect
        if (!userInitiatedDisconnectRef.current) {
          const reason = data?.reason || data?.code || 'Unknown reason'
          showToast(`Call ended unexpectedly: ${reason}`, 'error')
        }
        userInitiatedDisconnectRef.current = false // Reset flag
      })

      // Handle disconnect/reconnect events (for network issues)
      client.on('disconnect', () => {
        console.log('Disconnected (network issue)')
        showToast('Connection lost. Attempting to reconnect...', 'error')
      })

      client.on('reconnect', () => {
        console.log('Reconnected')
        showToast('Connection restored', 'success')
      })

      client.on('update', (update: any) => {
        console.log('Update:', update)
        // You can access transcript with update.transcript
        if (update.transcript) {
          console.log('Transcript:', update.transcript)
        }
        // Check for any error information in the update
        if (update.error) {
          console.error('Update contains error:', update.error)
        }
      })

      client.on('audio', (_audio: Uint8Array) => {
        // Audio data received from server
        // Audio data is available but not used in this implementation
        console.log('Audio received')
      })

      client.on('error', (error: any) => {
        console.error('Retell error:', error)
        console.error('Error details:', JSON.stringify(error, null, 2))
        setIsConnecting(false)
        setIsConnected(false)
        const errorMessage = error?.message || error?.error || String(error) || 'Unknown error'
        showToast(`Error: ${errorMessage}`, 'error')
        // Don't stop conversation here - let Retell SDK handle it
      })

      // NOW create the web call - we have mic permission ready
      console.log('Creating web call...')
      const webCallResponse = await apiClient.createWebCall({
        agent_id: fullAgent.id,
        metadata: {},
        retell_llm_dynamic_variables: {},
        custom_sip_headers: {},
      })

      if (!webCallResponse.call_id || !webCallResponse.access_token) {
        throw new Error('No call_id or access_token received from server')
      }

      // Start the call IMMEDIATELY after getting access_token
      // Retell requires joining within 30 seconds of create_web_call
      const sampleRate = webCallResponse.sample_rate || 24000
      console.log('Starting call immediately with accessToken and callId:', webCallResponse.call_id, 'sampleRate:', sampleRate)
      
      // Start call - SDK will handle getting the microphone stream
      await client.startCall({
        accessToken: webCallResponse.access_token,
        callId: webCallResponse.call_id,
        sampleRate: sampleRate,
      })
      console.log('startCall completed')
    } catch (error: any) {
      console.error('Failed to connect:', error)
      setIsConnecting(false)
      setIsConnected(false)
      showToast(`Failed to connect: ${error.response?.data?.detail || error.message || 'Unknown error'}`, 'error')
    }
  }

  const handleDisconnect = async () => {
    if (retellClientRef.current) {
      try {
        userInitiatedDisconnectRef.current = true // Mark as user-initiated
        retellClientRef.current.stopCall()
        setIsConnected(false)
        showToast('Disconnected', 'success')
      } catch (error: any) {
        console.error('Failed to disconnect:', error)
        showToast(`Failed to disconnect: ${error.message || 'Unknown error'}`, 'error')
        // Force cleanup even if disconnect fails
        setIsConnected(false)
        userInitiatedDisconnectRef.current = false
      }
    }
  }

  const handleCloseModal = () => {
    if (isConnected && retellClientRef.current) {
      handleDisconnect()
    }
    setShowModal(false)
    setIsConnecting(false)
    setIsConnected(false)
  }

  const handleViewCallRecording = (callShortId: string) => {
    navigate(`/playground/call-recordings/${callShortId}`)
  }

  const deleteMutation = useMutation({
    mutationFn: (callShortId: string) => apiClient.deleteCallRecording(callShortId),
    onSuccess: () => {
      showToast('Call recording deleted successfully', 'success')
      queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
    },
    onError: (error: any) => {
      showToast(`Failed to delete: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const handleDeleteCallRecording = (callShortId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (window.confirm('Are you sure you want to delete this call recording? This action cannot be undone.')) {
      deleteMutation.mutate(callShortId)
    }
  }

  const handleRefreshCallRecording = async (callShortId: string) => {
    try {
      await apiClient.refreshCallRecording(callShortId)
      showToast('Call recording refresh initiated', 'success')
      // Refetch after a delay
      setTimeout(() => {
        refetchCallRecordings()
      }, 2000)
    } catch (error: any) {
      showToast(`Failed to refresh: ${error.response?.data?.detail || error.message}`, 'error')
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
              variant="outline"
              onClick={() => refetchCallRecordings()}
              leftIcon={<RefreshCw className="h-4 w-4" />}
            >
              Refresh Recordings
            </Button>
            <Button
              variant="primary"
              onClick={() => setShowModal(true)}
              leftIcon={<Play className="h-5 w-5" />}
              disabled={!selectedAgent || !canMakeCall}
            >
              Play
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
          ) : !canMakeCall ? (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm text-blue-800">
                <strong>Selected Agent:</strong> {selectedAgent.name}
              </p>
              <p className="text-sm text-blue-700 mt-2">
                {!hasWebCallEnabled && 'This agent does not have web calling enabled. '}
                {!isRetellAgent && 'This agent is not configured with a Retell integration. '}
                {!fullAgent?.voice_ai_agent_id && 'This agent does not have a Retell agent ID configured. '}
                Please configure your agent with Retell integration and enable web calling to use the playground.
              </p>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <p className="text-sm text-green-800">
                <strong>Ready to test:</strong> {selectedAgent.name}
              </p>
              <p className="text-sm text-green-700 mt-1">
                Click the Play button to start a web call with your Retell agent.
              </p>
            </div>
          )}

          {/* Call Recordings Section - Always Visible */}
          <div className="mt-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-md font-semibold text-gray-900">Call Recordings</h3>
            </div>
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
                              className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                                recording.status === 'UPDATED'
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
        </div>
      </div>

      {/* Connect Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Connect to Agent</h3>
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
                    This agent is not configured for Retell web calls.
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
                      Retell Agent ID: {fullAgent?.voice_ai_agent_id}
                    </p>
                  </div>

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
    </>
  )
}

