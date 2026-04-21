/**
 * Voice Agent Component
 * 
 * This component connects to a Pipecat voice agent using WebSocket.
 * It uses the Pipecat client library to handle real-time voice interactions.
 */

import { useState, useRef, useEffect } from 'react'
import { PipecatClient, PipecatClientOptions, RTVIEvent } from '@pipecat-ai/client-js'
import { WebSocketTransport } from '@pipecat-ai/websocket-transport'
import ReactMarkdown from 'react-markdown'
import { Mic, MicOff, Loader, MessageSquare, AlertTriangle } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import Button from './Button'
import { useAgentStore } from '../store/agentStore'
import { apiClient } from '../lib/api'

interface VoiceAgentProps {
  personaId?: string
  scenarioId?: string
  agentId?: string
  customEndpoint?: string
  customEndpointLabel?: string
  onSessionSaved?: () => void
}

type TranscriptEntry = { role: 'user' | 'agent'; content: string; timestamp: string }

export default function VoiceAgent({ personaId, scenarioId, agentId, customEndpoint, customEndpointLabel, onSessionSaved }: VoiceAgentProps) {
  const { selectedAgent } = useAgentStore()
  
  // Use agentId prop if provided, otherwise fall back to selectedAgent from store
  const effectiveAgentId = agentId || selectedAgent?.id
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [status, setStatus] = useState<string>('Disconnected')
  const [error, setError] = useState<string | null>(null)
  const [logs, setLogs] = useState<Array<{ timestamp: string; message: string; type: 'user' | 'bot' | 'system' }>>([])
  const [transcriptEntries, setTranscriptEntries] = useState<TranscriptEntry[]>([])
  const [sessionStartedAt, setSessionStartedAt] = useState<string | null>(null)
  const [sessionEndedAt, setSessionEndedAt] = useState<string | null>(null)
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null)
  const [isSavingSession, setIsSavingSession] = useState(false)
  const [savedCallShortId, setSavedCallShortId] = useState<string | null>(null)
  const [isEvaluatingSavedSession, setIsEvaluatingSavedSession] = useState(false)
  const formatErrorMessage = (rawError: any) => {
    if (!rawError) return 'Unknown error'
    if (typeof rawError === 'string') return rawError
    if (typeof rawError?.message === 'string') return rawError.message
    if (typeof rawError?.data?.message === 'string') return rawError.data.message
    if (typeof rawError?.data?.detail === 'string') return rawError.data.detail
    return JSON.stringify(rawError)
  }

  const getCustomEndpointCompatibilityError = (endpoint: string) => {
    try {
      const parsed = new URL(endpoint)
      const host = parsed.hostname.toLowerCase()
      const path = parsed.pathname.toLowerCase()

      // This component uses Pipecat's RTVI websocket protocol.
      // Raw provider websocket URLs (e.g. ElevenLabs ConvAI) are not RTVI-compatible.
      if (host.includes('api.elevenlabs.io') && path.includes('/v1/convai/conversation')) {
        return 'This is a native ElevenLabs websocket URL, not an RTVI websocket endpoint. Use the Voice AI Agent flow for ElevenLabs, or connect through an RTVI-compatible bridge endpoint.'
      }
    } catch {
      return null
    }

    return null
  }


  const { data: s3Status } = useQuery({
    queryKey: ['s3-status'],
    queryFn: () => apiClient.getS3Status(),
    staleTime: 60_000,
  })

  const pcClientRef = useRef<PipecatClient | null>(null)
  const botAudioRef = useRef<HTMLAudioElement | null>(null)
  const isConnectingRef = useRef(false) // Guard to prevent multiple simultaneous connections
  const micStreamRef = useRef<MediaStream | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const recordedChunksRef = useRef<Blob[]>([])

  const appendTranscript = (entry: TranscriptEntry) => {
    setTranscriptEntries((prev) => [...prev, entry])
  }

  const startRecording = (botTrack?: MediaStreamTrack) => {
    if (mediaRecorderRef.current || typeof MediaRecorder === 'undefined') return

    const tracks: MediaStreamTrack[] = []
    if (botTrack) {
      tracks.push(botTrack)
    } else if (botAudioRef.current?.srcObject && 'getAudioTracks' in botAudioRef.current.srcObject) {
      tracks.push(...botAudioRef.current.srcObject.getAudioTracks())
    }

    if (micStreamRef.current) {
      tracks.push(...micStreamRef.current.getAudioTracks())
    }

    if (tracks.length === 0) return

    try {
      const stream = new MediaStream(tracks)
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const recorder = new MediaRecorder(stream, { mimeType })
      recordedChunksRef.current = []
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          recordedChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        if (recordedChunksRef.current.length > 0) {
          setRecordedBlob(new Blob(recordedChunksRef.current, { type: recorder.mimeType || 'audio/webm' }))
        }
      }
      recorder.start(1000)
      mediaRecorderRef.current = recorder
      log('Recording started', 'system')
    } catch (recorderError: any) {
      log(`Failed to start recording: ${recorderError?.message || String(recorderError)}`, 'system')
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    mediaRecorderRef.current = null
  }

  const handleSaveSession = async () => {
    if (!effectiveAgentId || !customEndpoint || transcriptEntries.length === 0) return

    try {
      setIsSavingSession(true)
      setError(null)
      const audioFile = recordedBlob
        ? new File([recordedBlob], `custom-websocket-${Date.now()}.webm`, { type: recordedBlob.type || 'audio/webm' })
        : undefined
      const response = await apiClient.createCustomWebsocketSession({
        agent_id: effectiveAgentId,
        websocket_url: customEndpoint,
        transcript_entries: transcriptEntries,
        started_at: sessionStartedAt || undefined,
        ended_at: sessionEndedAt || new Date().toISOString(),
        audio_file: audioFile,
      })
      setSavedCallShortId(response.call_short_id)
      log(`Session saved as call ${response.call_short_id}`, 'system')
      onSessionSaved?.()
    } catch (saveError: any) {
      const errorMessage = saveError?.response?.data?.detail || saveError?.message || 'Failed to save session'
      setError(errorMessage)
      log(`Save failed: ${errorMessage}`, 'system')
    } finally {
      setIsSavingSession(false)
    }
  }

  const handleEvaluateSavedSession = async () => {
    if (!savedCallShortId) return
    try {
      setIsEvaluatingSavedSession(true)
      await apiClient.evaluateCustomWebsocketSession(savedCallShortId)
      log(`Evaluation queued for ${savedCallShortId}`, 'system')
      onSessionSaved?.()
    } catch (evalError: any) {
      const errorMessage = evalError?.response?.data?.detail || evalError?.message || 'Failed to queue evaluation'
      setError(errorMessage)
      log(`Evaluation failed: ${errorMessage}`, 'system')
    } finally {
      setIsEvaluatingSavedSession(false)
    }
  }

  useEffect(() => {
    // Create audio element for bot audio playback
    const audio = document.createElement('audio')
    audio.autoplay = true
    botAudioRef.current = audio
    document.body.appendChild(audio)

    return () => {
      // Cleanup on unmount
      if (pcClientRef.current) {
        stopRecording()
        pcClientRef.current.disconnect().catch(console.error)
      }
      if (botAudioRef.current) {
        botAudioRef.current.remove()
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((track) => track.stop())
        micStreamRef.current = null
      }
    }
  }, [])

  const log = (message: string, type: 'user' | 'bot' | 'system' = 'system') => {
    const entry = {
      timestamp: new Date().toISOString(),
      message,
      type,
    }
    setLogs((prev) => [...prev, entry])
    console.log(`[${type.toUpperCase()}] ${message}`)
  }

  const updateStatus = (newStatus: string) => {
    setStatus(newStatus)
    log(`Status: ${newStatus}`, 'system')
  }

  const setupMediaTracks = () => {
    if (!pcClientRef.current) return

    const tracks = pcClientRef.current.tracks()
    if (tracks.bot?.audio && botAudioRef.current) {
      setupAudioTrack(tracks.bot.audio)
    }
  }

  const setupTrackListeners = () => {
    if (!pcClientRef.current) return

    // Listen for new tracks starting
    pcClientRef.current.on(RTVIEvent.TrackStarted, (track, participant) => {
      // Only handle non-local (bot) tracks
      if (!participant?.local && track.kind === 'audio' && botAudioRef.current) {
        setupAudioTrack(track)
      }
    })

    // Listen for tracks stopping
    pcClientRef.current.on(RTVIEvent.TrackStopped, (track, participant) => {
      log(
        `Track stopped: ${track.kind} from ${participant?.name || 'unknown'}`,
        'system'
      )
    })
  }

  const setupAudioTrack = (track: MediaStreamTrack) => {
    if (!botAudioRef.current) return

    log('Setting up audio track', 'system')

    if (
      botAudioRef.current.srcObject &&
      'getAudioTracks' in botAudioRef.current.srcObject
    ) {
      const oldTrack = botAudioRef.current.srcObject.getAudioTracks()[0]
      if (oldTrack?.id === track.id) return
    }

    botAudioRef.current.srcObject = new MediaStream([track])
    startRecording(track)
  }

  const connect = async () => {
    // Prevent multiple simultaneous connection attempts
    if (isConnectingRef.current) {
      log('Connection already in progress, ignoring duplicate request', 'system')
      return
    }

    if (pcClientRef.current) {
      log('Client already exists, disconnecting first...', 'system')
      try {
        await pcClientRef.current.disconnect()
      } catch (e) {
        // Ignore disconnect errors
      }
      pcClientRef.current = null
    }

    try {
      isConnectingRef.current = true
      setIsConnecting(true)
      setError(null)
      updateStatus('Connecting...')

      if (customEndpoint) {
        const compatibilityError = getCustomEndpointCompatibilityError(customEndpoint)
        if (compatibilityError) {
          setError(compatibilityError)
          log(`Error: ${compatibilityError}`, 'system')
          updateStatus('Error')
          setIsConnecting(false)
          setIsConnected(false)
          return
        }
      }

      // Get API key and set it as a cookie for startBotAndConnect
      const apiKey = localStorage.getItem('apiKey')
      if (!apiKey) {
        throw new Error('API key not found. Please log in first.')
      }

      if (!customEndpoint) {
        // Set API key as a cookie so startBotAndConnect can send it
        // The backend /connect endpoint checks cookies first
        document.cookie = `api_key=${apiKey}; path=/; SameSite=Lax`
        log('API key set as cookie for authentication', 'system')
      } else {
        log('Using custom endpoint, skipping backend API cookie flow', 'system')
      }
      setSavedCallShortId(null)
      setRecordedBlob(null)
      setTranscriptEntries([])
      setSessionStartedAt(new Date().toISOString())
      setSessionEndedAt(null)

      try {
        micStreamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch {
        micStreamRef.current = null
        log('Microphone stream unavailable for local recording', 'system')
      }

      // Create WebSocketTransport
      // Note: WebSocketTransport might need endpoint URL for RTVI protocol initialization
      // But the constructor doesn't accept parameters, so we'll set it after creation
      const transport = new WebSocketTransport()

      const PipecatConfig: PipecatClientOptions = {
        transport: transport,
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            updateStatus('Connected')
            setIsConnected(true)
            setIsConnecting(false)
            log('✅ Successfully connected to WebSocket', 'system')
          },
          onDisconnected: () => {
            updateStatus('Disconnected')
            setIsConnected(false)
            setIsConnecting(false)
            setSessionEndedAt(new Date().toISOString())
            stopRecording()
            log('Client disconnected', 'system')
          },
          onBotReady: (data) => {
            log(`Bot ready: ${JSON.stringify(data)}`, 'system')
            setupMediaTracks()
          },
          onUserTranscript: (data) => {
            if (data.final) {
              log(`User: ${data.text}`, 'user')
              appendTranscript({ role: 'user', content: data.text, timestamp: new Date().toISOString() })
            }
          },
          onBotTranscript: (data) => {
            log(`Bot: ${data.text}`, 'bot')
            appendTranscript({ role: 'agent', content: data.text, timestamp: new Date().toISOString() })
          },
          onMessageError: (error: any) => {
            console.error('Message error:', error)
            const errorMessage = formatErrorMessage(error)
            log(`Error: ${errorMessage}`, 'system')
          },
          onError: (error: any) => {
            console.error('Error:', error)
            const errorMessage = formatErrorMessage(error)
            setError(errorMessage)
            log(`Error: ${errorMessage}`, 'system')
          },
        },
      }

      const pcClient = new PipecatClient(PipecatConfig)
      pcClientRef.current = pcClient

        // Expose for debugging
        ; (window as any).pcClient = pcClient

      setupTrackListeners()

      log('Initializing devices...', 'system')
      await pcClient.initDevices()

      // Use startBotAndConnect exactly like the Pipecat example
      // This handles RTVI protocol handshake automatically
      let endpointUrl = customEndpoint || `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/v1/voice-agent/connect`

      // Append agent_id, persona_id and scenario_id if present
      const params = new URLSearchParams()
      if (!customEndpoint && effectiveAgentId) {
        params.append('agent_id', effectiveAgentId)
      }
      if (!customEndpoint && personaId) params.append('persona_id', personaId)
      if (!customEndpoint && scenarioId) params.append('scenario_id', scenarioId)

      if (!customEndpoint && params.toString()) {
        endpointUrl += `?${params.toString()}`
      }

      log(`Connecting to bot endpoint: ${endpointUrl}`, 'system')
      const endpointProtocol = endpointUrl.startsWith('wss://') || endpointUrl.startsWith('ws://')
        ? 'websocket'
        : 'http'

      if (endpointProtocol === 'websocket') {
        log('Using direct connect() for websocket URL...', 'system')
        await pcClient.connect({ wsUrl: endpointUrl })
        log('✅ WebSocket transport connected', 'system')
      } else {
        log('Using startBotAndConnect() - this will handle RTVI protocol handshake...', 'system')
        await pcClient.startBotAndConnect({
          endpoint: endpointUrl,
        })
        log('✅ Connection established and RTVI handshake complete!', 'system')
      }
    } catch (error: any) {
      const errorMessage = formatErrorMessage(error) || 'Failed to connect'
      setError(errorMessage)
      log(`Error connecting: ${errorMessage}`, 'system')
      updateStatus('Error')
      setIsConnecting(false)
      setIsConnected(false)

      // Clean up if there's an error
      if (pcClientRef.current) {
        try {
          await pcClientRef.current.disconnect()
        } catch (disconnectError: any) {
          // Ignore disconnect errors - they're expected if connection failed
          log(`Error during disconnect (expected if connection failed): ${disconnectError?.message || String(disconnectError)}`, 'system')
        } finally {
          pcClientRef.current = null
        }
      }
    } finally {
      // Always reset the connection guard
      isConnectingRef.current = false
    }
  }

  const disconnect = async () => {
    if (pcClientRef.current) {
      try {
        stopRecording()
        await pcClientRef.current.disconnect()
        pcClientRef.current = null

        if (
          botAudioRef.current?.srcObject &&
          'getAudioTracks' in botAudioRef.current.srcObject
        ) {
          botAudioRef.current.srcObject
            .getAudioTracks()
            .forEach((track) => track.stop())
          botAudioRef.current.srcObject = null
        }

        updateStatus('Disconnected')
        setIsConnected(false)
        setSessionEndedAt(new Date().toISOString())
        log('Disconnected successfully', 'system')
      } catch (error: any) {
        const errorMessage = error?.message || 'Failed to disconnect'
        setError(errorMessage)
        log(`Error disconnecting: ${errorMessage}`, 'system')
      } finally {
        // Ensure state is reset even if disconnect fails
        pcClientRef.current = null
        stopRecording()
        setIsConnected(false)
        setIsConnecting(false)
      }
    }
  }

  // Get agent name for display - use selectedAgent if available, otherwise use generic
  const agentName = selectedAgent?.name || 'Voice Agent'
  const agentDescription = selectedAgent?.description || 'Interact with a real-time voice AI agent'

  return (
    <div className="space-y-6">
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{agentName}</h2>
            {customEndpoint && (
              <p className="text-xs text-gray-500 mt-1">
                {customEndpointLabel || 'WebSocket URL'}: <span className="font-mono">{customEndpoint}</span>
              </p>
            )}
            {selectedAgent?.description ? (
              <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700 mt-2 max-h-48 overflow-y-auto pr-1">
                <ReactMarkdown>{agentDescription}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-sm text-gray-600 mt-1">{agentDescription}</p>
            )}
          </div>
        </div>

        {s3Status && !s3Status.enabled && (
          <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
            <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-800">Storage not configured</p>
              <p className="text-xs text-amber-700 mt-0.5">
                Audio recordings will not be saved. Transcripts and analysis will still be captured from the live conversation.
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              {isConnected ? (
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
                  <span className="text-sm font-medium text-gray-700">Connected</span>
                </div>
              ) : (
                <span className="text-sm text-gray-500">{status}</span>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            {!isConnected ? (
              <Button
                onClick={connect}
                isLoading={isConnecting}
                leftIcon={isConnecting ? <Loader className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
                disabled={isConnecting}
              >
                Connect
              </Button>
            ) : (
              <Button
                onClick={disconnect}
                variant="danger"
                leftIcon={<MicOff className="h-4 w-4" />}
              >
                Disconnect
              </Button>
            )}
          </div>
        </div>

        {/* Debug Log */}
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Debug Log</h3>
          </div>
          <div className="h-64 overflow-y-auto bg-white rounded border border-gray-200 p-3 font-mono text-xs">
            {logs.length === 0 ? (
              <p className="text-gray-500 text-center py-8">No logs yet. Connect to start.</p>
            ) : (
              logs.map((log, idx) => (
                <div
                  key={idx}
                  className={`mb-1 ${log.type === 'user'
                      ? 'text-blue-600'
                      : log.type === 'bot'
                        ? 'text-green-600'
                        : 'text-gray-600'
                    }`}
                >
                  <span className="text-gray-400">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>{' '}
                  - {log.message}
                </div>
              ))
            )}
          </div>
        </div>

        {customEndpoint && !isConnected && transcriptEntries.length > 0 && (
          <div className="mt-4 rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900">Save Test Session</h3>
            <p className="mt-1 text-xs text-gray-600">
              Save transcript{recordedBlob ? ' + recording' : ''} so you can evaluate this call later.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={handleSaveSession} isLoading={isSavingSession} disabled={isSavingSession}>
                {savedCallShortId ? 'Saved' : 'Save Session'}
              </Button>
              {savedCallShortId && (
                <Button
                  variant="outline"
                  onClick={handleEvaluateSavedSession}
                  isLoading={isEvaluatingSavedSession}
                  disabled={isEvaluatingSavedSession}
                >
                  Run Evaluation
                </Button>
              )}
            </div>
            {savedCallShortId && (
              <p className="mt-2 text-xs text-green-700">
                Saved as call ID <span className="font-mono font-semibold">{savedCallShortId}</span>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

