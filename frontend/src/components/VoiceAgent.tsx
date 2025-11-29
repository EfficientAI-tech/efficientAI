/**
 * Voice Agent Component
 * 
 * This component connects to a Pipecat voice agent using WebSocket.
 * It uses the Pipecat client library to handle real-time voice interactions.
 */

import { useState, useRef, useEffect } from 'react'
import { PipecatClient, PipecatClientOptions, RTVIEvent } from '@pipecat-ai/client-js'
import { WebSocketTransport } from '@pipecat-ai/websocket-transport'
import { Mic, MicOff, Loader, MessageSquare } from 'lucide-react'
import Button from './Button'
import { useAgentStore } from '../store/agentStore'

interface VoiceAgentProps {
  personaId?: string
  scenarioId?: string
}

export default function VoiceAgent({ personaId, scenarioId }: VoiceAgentProps) {
  const { selectedAgent } = useAgentStore()
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [status, setStatus] = useState<string>('Disconnected')
  const [error, setError] = useState<string | null>(null)
  const [logs, setLogs] = useState<Array<{ timestamp: string; message: string; type: 'user' | 'bot' | 'system' }>>([])

  const pcClientRef = useRef<PipecatClient | null>(null)
  const botAudioRef = useRef<HTMLAudioElement | null>(null)
  const isConnectingRef = useRef(false) // Guard to prevent multiple simultaneous connections

  useEffect(() => {
    // Create audio element for bot audio playback
    const audio = document.createElement('audio')
    audio.autoplay = true
    botAudioRef.current = audio
    document.body.appendChild(audio)

    return () => {
      // Cleanup on unmount
      if (pcClientRef.current) {
        pcClientRef.current.disconnect().catch(console.error)
      }
      if (botAudioRef.current) {
        botAudioRef.current.remove()
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

      // Get API key and set it as a cookie for startBotAndConnect
      const apiKey = localStorage.getItem('apiKey')
      if (!apiKey) {
        throw new Error('API key not found. Please log in first.')
      }

      // Set API key as a cookie so startBotAndConnect can send it
      // The backend /connect endpoint checks cookies first
      document.cookie = `api_key=${apiKey}; path=/; SameSite=Lax`

      log('API key set as cookie for authentication', 'system')

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
            log('Client disconnected', 'system')
          },
          onBotReady: (data) => {
            log(`Bot ready: ${JSON.stringify(data)}`, 'system')
            setupMediaTracks()
          },
          onUserTranscript: (data) => {
            if (data.final) {
              log(`User: ${data.text}`, 'user')
            }
          },
          onBotTranscript: (data) => {
            log(`Bot: ${data.text}`, 'bot')
          },
          onMessageError: (error: any) => {
            console.error('Message error:', error)
            const errorMessage = (error && typeof error === 'object' && 'message' in error)
              ? error.message
              : String(error)
            log(`Error: ${errorMessage}`, 'system')
          },
          onError: (error: any) => {
            console.error('Error:', error)
            const errorMessage = (error && typeof error === 'object' && 'message' in error)
              ? error.message
              : String(error)
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
      let endpointUrl = `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/v1/voice-agent/connect`

      // Append agent_id, persona_id and scenario_id if present
      const params = new URLSearchParams()
      if (selectedAgent?.id) {
        params.append('agent_id', selectedAgent.id)
      }
      if (personaId) params.append('persona_id', personaId)
      if (scenarioId) params.append('scenario_id', scenarioId)

      if (params.toString()) {
        endpointUrl += `?${params.toString()}`
      }

      log(`Connecting to bot endpoint: ${endpointUrl}`, 'system')
      log('Using startBotAndConnect() - this will handle RTVI protocol handshake...', 'system')

      await pcClient.startBotAndConnect({
        endpoint: endpointUrl,
      })

      log('✅ Connection established and RTVI handshake complete!', 'system')
    } catch (error: any) {
      const errorMessage = error?.response?.data?.detail || error?.message || String(error) || 'Failed to connect'
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
        log('Disconnected successfully', 'system')
      } catch (error: any) {
        const errorMessage = error?.message || 'Failed to disconnect'
        setError(errorMessage)
        log(`Error disconnecting: ${errorMessage}`, 'system')
      } finally {
        // Ensure state is reset even if disconnect fails
        pcClientRef.current = null
        setIsConnected(false)
        setIsConnecting(false)
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Voice Agent (Gemini)</h2>
            <p className="text-sm text-gray-600 mt-1">
              Interact with a real-time voice AI agent powered by Google Gemini
            </p>
          </div>
        </div>

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
      </div>
    </div>
  )
}

