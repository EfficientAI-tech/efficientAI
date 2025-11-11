import { useState, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { Play, Square, Loader, MessageSquare } from 'lucide-react'
import Button from '../components/Button'
import { TestAgentConversation } from '../types/api'

export default function EvaluateTestAgents() {
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [selectedPersona, setSelectedPersona] = useState<string>('')
  const [selectedScenario, setSelectedScenario] = useState<string>('')
  const [selectedVoiceBundle, setSelectedVoiceBundle] = useState<string>('')
  const [conversation, setConversation] = useState<TestAgentConversation | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const conversationStartTimeRef = useRef<number>(0)
  const responseAudioRef = useRef<HTMLAudioElement | null>(null)
  const conversationRef = useRef<TestAgentConversation | null>(null)
  const isProcessingRef = useRef<boolean>(false)

  // Fetch agents, personas, scenarios, voice bundles
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: personas = [] } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  const { data: voiceBundles = [] } = useQuery({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  // Create conversation mutation
  const createConversationMutation = useMutation<TestAgentConversation, Error, {
    agent_id: string
    persona_id: string
    scenario_id: string
    voice_bundle_id: string
  }>({
    mutationFn: (data: {
      agent_id: string
      persona_id: string
      scenario_id: string
      voice_bundle_id: string
    }) => apiClient.createTestAgentConversation(data),
    onSuccess: (data: TestAgentConversation) => {
      setConversation(data)
      setError(null)
    },
    onError: (error: any) => {
      setError(error.response?.data?.detail || 'Failed to create conversation')
    },
  })

  // Start conversation mutation
  const startConversationMutation = useMutation<TestAgentConversation, Error, string>({
    mutationFn: (conversationId: string) => apiClient.startTestAgentConversation(conversationId),
    onSuccess: (data: TestAgentConversation) => {
      setConversation(data)
      conversationRef.current = data
      conversationStartTimeRef.current = Date.now()
      startRecording()
    },
    onError: (error: any) => {
      setError(error.response?.data?.detail || 'Failed to start conversation')
    },
  })

  // Process audio mutation
  const processAudioMutation = useMutation({
    mutationFn: async ({ conversationId, audioBlob, timestamp }: {
      conversationId: string
      audioBlob: Blob
      timestamp: number
    }) => {
      const audioFile = new File([audioBlob], 'audio.wav', { type: 'audio/wav' })
      return apiClient.processTestAgentAudio(conversationId, audioFile, timestamp)
    },
    onSuccess: async (data, variables) => {
      // Play response audio
      if (data.audio_url) {
        await playResponseAudio(variables.conversationId)
      }
      
      // Refresh conversation to get updated transcription
      const updated: TestAgentConversation = await apiClient.getTestAgentConversation(variables.conversationId)
      setConversation(updated)
      conversationRef.current = updated
      isProcessingRef.current = false
      setIsProcessing(false)
    },
    onError: (error: any) => {
      setError(error.response?.data?.detail || 'Failed to process audio')
      isProcessingRef.current = false
      setIsProcessing(false)
    },
  })

  // End conversation mutation
  const endConversationMutation = useMutation<TestAgentConversation, Error, { conversationId: string; finalAudioKey?: string }>({
    mutationFn: ({ conversationId, finalAudioKey }: { conversationId: string; finalAudioKey?: string }) =>
      apiClient.endTestAgentConversation(conversationId, finalAudioKey) as Promise<TestAgentConversation>,
    onSuccess: (data: TestAgentConversation) => {
      setConversation(data)
      stopRecording()
    },
    onError: (error: any) => {
      setError(error.response?.data?.detail || 'Failed to end conversation')
    },
  })

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      
      // Try to use a format that OpenAI supports (WAV or MP3)
      // Fallback to WebM if not supported
      let mimeType = 'audio/webm;codecs=opus'
      if (MediaRecorder.isTypeSupported('audio/webm')) {
        mimeType = 'audio/webm;codecs=opus'
      } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
        mimeType = 'audio/mp4'
      }
      
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: mimeType,
      })

      audioChunksRef.current = []

      mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && conversationRef.current) {
          audioChunksRef.current.push(event.data)
          
          // Process audio chunk when we have enough data (every 2-3 seconds)
          if (audioChunksRef.current.length >= 2 && !isProcessingRef.current) {
            const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
            const timestamp = (Date.now() - conversationStartTimeRef.current) / 1000
            
            // Clear chunks after processing
            audioChunksRef.current = []
            
            isProcessingRef.current = true
            setIsProcessing(true)
            try {
              await processAudioMutation.mutateAsync({
                conversationId: conversationRef.current.id,
                audioBlob,
                timestamp,
              })
            } catch (error) {
              console.error('Error processing audio:', error)
              isProcessingRef.current = false
              setIsProcessing(false)
            }
          }
        }
      }

      mediaRecorder.onstop = () => {
        // Process any remaining chunks
        if (conversationRef.current && audioChunksRef.current.length > 0) {
          const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
          const timestamp = (Date.now() - conversationStartTimeRef.current) / 1000
          
          processAudioMutation.mutate({
            conversationId: conversationRef.current.id,
            audioBlob,
            timestamp,
          })
        }

        stream.getTracks().forEach(track => track.stop())
      }

      mediaRecorderRef.current = mediaRecorder
      mediaRecorder.start(1000) // Collect data every second
      setIsRecording(true)
    } catch (err) {
      setError('Failed to access microphone. Please check permissions.')
      console.error('Error accessing microphone:', err)
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
    }
  }

  const playResponseAudio = async (conversationId: string) => {
    try {
      const audioBlob = await apiClient.getTestAgentResponseAudio(conversationId)
      const audioUrl = URL.createObjectURL(audioBlob)
      
      if (responseAudioRef.current) {
        responseAudioRef.current.src = audioUrl
        responseAudioRef.current.play()
      } else {
        const audio = new Audio(audioUrl)
        responseAudioRef.current = audio
        audio.play()
        audio.onended = () => {
          URL.revokeObjectURL(audioUrl)
        }
      }
    } catch (error) {
      console.error('Error playing response audio:', error)
    }
  }

  const handleStart = async () => {
    if (!selectedAgent || !selectedPersona || !selectedScenario || !selectedVoiceBundle) {
      setError('Please select all required options')
      return
    }

    setError(null)
    
    // Create conversation
    const newConversation = await createConversationMutation.mutateAsync({
      agent_id: selectedAgent,
      persona_id: selectedPersona,
      scenario_id: selectedScenario,
      voice_bundle_id: selectedVoiceBundle,
    })

    // Start conversation
    await startConversationMutation.mutateAsync((newConversation as TestAgentConversation).id)
  }

  const handleStop = async () => {
    if (!conversation) return

    stopRecording()

    await endConversationMutation.mutateAsync({
      conversationId: conversation.id,
    })
  }

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const getElapsedTime = (): number => {
    if (!conversation || !conversation.started_at) return 0
    return (Date.now() - new Date(conversation.started_at).getTime()) / 1000
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluate Test Agents</h1>
          <p className="mt-2 text-sm text-gray-600">
            Test your voice AI agents by having live conversations with test agents
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {/* Configuration */}
      {!conversation && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Configuration</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Agent
              </label>
              {agents.length === 0 ? (
                <div className="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50">
                  <p className="text-sm text-gray-500 mb-2">No agents available</p>
                  <Link
                    to="/agents"
                    className="text-sm text-primary-600 hover:text-primary-700 font-medium"
                  >
                    Create your first agent →
                  </Link>
                </div>
              ) : (
                <select
                  value={selectedAgent}
                  onChange={(e) => setSelectedAgent(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                >
                  <option value="">Select an agent</option>
                  {agents.map((agent: any) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Persona
              </label>
              <select
                value={selectedPersona}
                onChange={(e) => setSelectedPersona(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="">Select a persona</option>
                {personas.map((persona: any) => (
                  <option key={persona.id} value={persona.id}>
                    {persona.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Scenario
              </label>
              <select
                value={selectedScenario}
                onChange={(e) => setSelectedScenario(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="">Select a scenario</option>
                {scenarios.map((scenario: any) => (
                  <option key={scenario.id} value={scenario.id}>
                    {scenario.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Voice Bundle
              </label>
              <select
                value={selectedVoiceBundle}
                onChange={(e) => setSelectedVoiceBundle(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="">Select a voice bundle</option>
                {voiceBundles.map((bundle: any) => (
                  <option key={bundle.id} value={bundle.id}>
                    {bundle.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-6">
            <Button
              onClick={handleStart}
              isLoading={createConversationMutation.isPending || startConversationMutation.isPending}
              leftIcon={<Play className="h-4 w-4" />}
            >
              Start Evaluation
            </Button>
          </div>
        </div>
      )}

      {/* Active Conversation */}
      {conversation && (
        <div className="space-y-6">
          {/* Controls */}
          <div className="bg-white shadow rounded-lg p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  {isRecording ? (
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 bg-red-500 rounded-full animate-pulse"></div>
                      <span className="text-sm font-medium text-gray-700">Recording</span>
                    </div>
                  ) : (
                    <span className="text-sm text-gray-500">Not recording</span>
                  )}
                </div>
                {conversation.started_at && (
                  <div className="text-sm text-gray-600">
                    Duration: {formatTime(getElapsedTime())}
                  </div>
                )}
                {isProcessing && (
                  <div className="flex items-center gap-2 text-sm text-blue-600">
                    <Loader className="h-4 w-4 animate-spin" />
                    Processing...
                  </div>
                )}
              </div>
              <Button
                onClick={handleStop}
                variant="danger"
                leftIcon={<Square className="h-4 w-4" />}
                isLoading={endConversationMutation.isPending}
              >
                End Conversation
              </Button>
            </div>
          </div>

          {/* Live Transcription */}
          <div className="bg-white shadow rounded-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <MessageSquare className="h-5 w-5 text-gray-500" />
              <h2 className="text-lg font-semibold text-gray-900">Live Transcription</h2>
            </div>
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {conversation.live_transcription && conversation.live_transcription.length > 0 ? (
                conversation.live_transcription.map((turn, idx) => (
                  <div
                    key={idx}
                    className={`p-3 rounded-lg ${
                      turn.speaker === 'test_agent'
                        ? 'bg-blue-50 border-l-4 border-blue-500'
                        : 'bg-gray-50 border-l-4 border-gray-400'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-600">
                        {turn.speaker === 'test_agent' ? 'Test Agent' : 'You'}
                      </span>
                      <span className="text-xs text-gray-500">
                        {formatTime(turn.timestamp)}
                      </span>
                    </div>
                    <p className="text-sm text-gray-900">{turn.text}</p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-gray-500 text-center py-8">
                  No transcription yet. Start speaking to begin the conversation.
                </p>
              )}
            </div>
          </div>

          {/* Status */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Conversation Status</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-sm text-gray-500">Status:</span>
                <span className="ml-2 text-sm font-medium text-gray-900 capitalize">
                  {conversation.status}
                </span>
              </div>
              {conversation.duration_seconds && (
                <div>
                  <span className="text-sm text-gray-500">Total Duration:</span>
                  <span className="ml-2 text-sm font-medium text-gray-900">
                    {formatTime(conversation.duration_seconds)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Hidden audio element for playback */}
      <audio ref={responseAudioRef} />
    </div>
  )
}

