import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Phone, PhoneOff, Loader2, Mic } from 'lucide-react'
import { RetellWebClient } from 'retell-client-js-sdk'
import Vapi from '@vapi-ai/web'
import { Conversation } from '@elevenlabs/client'
import { apiClient } from '../../../lib/api'
import { Integration, IntegrationPlatform } from '../../../types/api'
import { getIntegrationPlatformLabel } from '../../../config/providers'
import VoiceAgent from '../../../components/VoiceAgent'
import VoiceOrb, { VoiceOrbSpeaker } from '../../../components/VoiceOrb'

export type AgentTalkMode = 'test_agent' | 'voice_ai_agent'

type RetellWebClientWithMethods = RetellWebClient & {
  startCall: (config: {
    accessToken: string
    sampleRate?: number
    callId?: string
  }) => Promise<void>
  stopCall: () => void
}

interface TalkAgent {
  id: string
  name: string
  description?: string | null
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
  voice_ai_agent_id?: string | null
}

interface AgentTalkSidebarProps {
  isOpen: boolean
  mode: AgentTalkMode
  agent: TalkAgent
  integrations: Integration[]
  onClose: () => void
  showToast: (message: string, type?: 'success' | 'error') => void
}

export default function AgentTalkSidebar({
  isOpen,
  mode,
  agent,
  integrations,
  onClose,
  showToast,
}: AgentTalkSidebarProps) {
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [transcripts, setTranscripts] = useState<Array<{ role: 'user' | 'agent'; content: string }>>([])
  const [activeSpeaker, setActiveSpeaker] = useState<VoiceOrbSpeaker>(null)

  const retellClientRef = useRef<RetellWebClientWithMethods | null>(null)
  const vapiClientRef = useRef<any>(null)
  const elevenLabsConversationRef = useRef<any>(null)
  const smallestClientRef = useRef<any>(null)
  const userInitiatedDisconnectRef = useRef(false)
  const wasOpenRef = useRef(false)
  const userSpeakingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pulseUserSpeaking = (durationMs = 1200) => {
    setActiveSpeaker('user')
    if (userSpeakingTimeoutRef.current) clearTimeout(userSpeakingTimeoutRef.current)
    userSpeakingTimeoutRef.current = setTimeout(() => {
      setActiveSpeaker((prev) => (prev === 'user' ? null : prev))
    }, durationMs)
  }

  useEffect(() => {
    return () => {
      if (userSpeakingTimeoutRef.current) clearTimeout(userSpeakingTimeoutRef.current)
    }
  }, [])

  const agentIntegration = agent.voice_ai_integration_id
    ? integrations.find((i) => i.id === agent.voice_ai_integration_id)
    : null

  const platform = agentIntegration?.platform
  const isRetell = platform === IntegrationPlatform.RETELL
  const isVapi = platform === IntegrationPlatform.VAPI
  const isElevenLabs = platform === IntegrationPlatform.ELEVENLABS
  const isSmallest = platform === IntegrationPlatform.SMALLEST

  const canTalkTest = mode === 'test_agent' && !!agent.voice_bundle_id
  const canTalkVoiceAI =
    mode === 'voice_ai_agent' &&
    !!agent.voice_ai_integration_id &&
    !!agent.voice_ai_agent_id &&
    (isRetell || isVapi || isElevenLabs || isSmallest)

  useEffect(() => {
    if (!isOpen || mode !== 'voice_ai_agent' || !canTalkVoiceAI) return
    if (isRetell && !retellClientRef.current) {
      retellClientRef.current = new RetellWebClient() as unknown as RetellWebClientWithMethods
    } else if (isVapi && !vapiClientRef.current && agentIntegration?.public_key) {
      vapiClientRef.current = new Vapi(agentIntegration.public_key)
    }
  }, [isOpen, mode, canTalkVoiceAI, isRetell, isVapi, agentIntegration?.public_key])

  useEffect(() => {
    if (wasOpenRef.current && !isOpen) {
      void handleDisconnect()
    }
    wasOpenRef.current = isOpen
  }, [isOpen])

  const handleDisconnect = async () => {
    userInitiatedDisconnectRef.current = true
    if (isRetell && retellClientRef.current) {
      try {
        retellClientRef.current.stopCall()
      } catch {
        /* ignore */
      }
    } else if (isVapi && vapiClientRef.current) {
      try {
        vapiClientRef.current.stop()
      } catch {
        /* ignore */
      }
    } else if (isElevenLabs && elevenLabsConversationRef.current) {
      try {
        await elevenLabsConversationRef.current.endSession()
      } catch {
        /* ignore */
      }
      elevenLabsConversationRef.current = null
    } else if (isSmallest && smallestClientRef.current) {
      try {
        smallestClientRef.current.stopSession()
      } catch {
        /* ignore */
      }
      smallestClientRef.current = null
    }
    setIsConnected(false)
    setIsConnecting(false)
    setActiveSpeaker(null)
    userInitiatedDisconnectRef.current = false
  }

  const handleConnectVoiceAI = async () => {
    if (!canTalkVoiceAI) return
    setIsConnecting(true)
    setTranscripts([])
    setActiveSpeaker(null)
    userInitiatedDisconnectRef.current = false

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((t) => t.stop())
    } catch {
      setIsConnecting(false)
      showToast('Microphone permission is required for voice calls', 'error')
      return
    }

    try {
      if (isRetell) {
        const client = retellClientRef.current!
        client.on('call_started', () => {
          setIsConnected(true)
          setIsConnecting(false)
        })
        client.on('agent_start_talking', () => setActiveSpeaker('agent'))
        client.on('agent_stop_talking', () => setActiveSpeaker((prev) => (prev === 'agent' ? null : prev)))
        client.on('update', (update: any) => {
          if (update.turntaking === 'user_turn') {
            pulseUserSpeaking()
          } else if (update.turntaking === 'agent_turn') {
            setActiveSpeaker('agent')
          }
          if (update.transcript) {
            const arr = Array.isArray(update.transcript)
              ? update.transcript
              : [{ role: update.role || 'agent', content: update.transcript }]
            setTranscripts(
              arr
                .filter((m: any) => m?.content)
                .map((m: any) => ({
                  role: m.role === 'user' ? ('user' as const) : ('agent' as const),
                  content: String(m.content),
                })),
            )
          }
        })
        client.on('call_ended', () => {
          setIsConnected(false)
          setIsConnecting(false)
          setActiveSpeaker(null)
        })
        client.on('error', () => {
          setIsConnecting(false)
          setIsConnected(false)
          setActiveSpeaker(null)
        })
        const webCall = await apiClient.createWebCall({ agent_id: agent.id, metadata: {} })
        await client.startCall({
          accessToken: webCall.access_token!,
          callId: webCall.call_id,
          sampleRate: webCall.sample_rate || 24000,
        })
      } else if (isVapi) {
        const client = vapiClientRef.current!
        client.on('call-start', () => {
          setIsConnected(true)
          setIsConnecting(false)
        })
        client.on('speech-start', () => setActiveSpeaker('agent'))
        client.on('speech-end', () => setActiveSpeaker((prev) => (prev === 'agent' ? null : prev)))
        client.on('message', (message: any) => {
          if (message.type === 'transcript') {
            if (message.transcriptType === 'partial' && message.role === 'user') {
              pulseUserSpeaking()
            }
            if (message.transcriptType === 'final') {
              setTranscripts((prev) => [
                ...prev,
                { role: message.role === 'user' ? 'user' : 'agent', content: message.transcript },
              ])
            }
          }
        })
        client.on('call-end', () => {
          setIsConnected(false)
          setIsConnecting(false)
          setActiveSpeaker(null)
        })
        await apiClient.createWebCall({ agent_id: agent.id, metadata: {} })
        await client.start(agent.voice_ai_agent_id!)
      } else if (isElevenLabs) {
        const webCall = await apiClient.createWebCall({ agent_id: agent.id, metadata: {} })
        if (!webCall.signed_url) throw new Error('No signed URL')
        const conversation = await Conversation.startSession({
          signedUrl: webCall.signed_url,
          onConnect: () => {
            setIsConnected(true)
            setIsConnecting(false)
          },
          onDisconnect: () => {
            setIsConnected(false)
            setIsConnecting(false)
            setActiveSpeaker(null)
            elevenLabsConversationRef.current = null
          },
          onModeChange: (mode: { mode?: string }) => {
            if (mode.mode === 'speaking') {
              setActiveSpeaker('agent')
            } else if (mode.mode === 'listening') {
              setActiveSpeaker((prev) => (prev === 'agent' ? null : prev))
            }
          },
          onMessage: (message: any) => {
            if (message?.source === 'user') {
              pulseUserSpeaking()
            }
            if (message?.source && message?.message) {
              setTranscripts((prev) => [
                ...prev,
                {
                  role: message.source === 'user' ? 'user' : 'agent',
                  content: message.message,
                },
              ])
            }
          },
          onError: () => {
            setIsConnecting(false)
            setIsConnected(false)
            setActiveSpeaker(null)
          },
        })
        elevenLabsConversationRef.current = conversation
      } else if (isSmallest) {
        const { AtomsClient } = await import('atoms-client-sdk')
        const webCall = await apiClient.createWebCall({ agent_id: agent.id, metadata: {} })
        if (!webCall.access_token || !webCall.host) throw new Error('Missing Smallest credentials')
        const client = new AtomsClient()
        smallestClientRef.current = client
        client.on('session_started', () => {
          setIsConnected(true)
          setIsConnecting(false)
        })
        client.on('session_ended', () => {
          setIsConnected(false)
          setIsConnecting(false)
          setActiveSpeaker(null)
        })
        client.on('transcript', (data: any) => {
          if (data?.text) {
            setActiveSpeaker('agent')
            setTranscripts((prev) => [...prev, { role: 'agent', content: data.text }])
          }
        })
        await client.startSession({
          accessToken: webCall.access_token,
          host: webCall.host,
          mode: 'webcall',
        })
        await client.startAudioPlayback()
      }
    } catch (err: any) {
      setIsConnecting(false)
      setIsConnected(false)
      setActiveSpeaker(null)
      showToast(err?.response?.data?.detail || err?.message || 'Failed to connect', 'error')
    }
  }

  if (!isOpen) return null

  const title =
    mode === 'test_agent'
      ? 'Talk to Test Agent'
      : `Talk to ${agentIntegration ? getIntegrationPlatformLabel(platform as IntegrationPlatform) : 'Voice AI'} Agent`

  const speakerHint =
    activeSpeaker === 'user'
      ? 'You are speaking…'
      : activeSpeaker === 'agent'
        ? 'Agent is speaking…'
        : isConnected
          ? 'Connected — speak naturally'
          : isConnecting
            ? 'Connecting…'
            : 'Tap to start a voice call'

  const panel = (
    <>
      <div className="fixed inset-0 bg-black/20 z-[90] lg:hidden" onClick={onClose} aria-hidden />
      <aside className="fixed inset-y-0 right-0 z-[100] w-full max-w-md bg-white border-l border-gray-200 shadow-2xl flex flex-col h-[100dvh]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div>
            <p className="text-sm font-semibold text-gray-900">{title}</p>
            <p className="text-xs text-gray-500 truncate max-w-[260px]">{agent.name}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              void handleDisconnect()
              onClose()
            }}
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
            aria-label="Close talk panel"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {mode === 'test_agent' ? (
            canTalkTest ? (
              <div className="flex-1 min-h-0 flex flex-col p-4">
                <VoiceAgent agentId={agent.id} compact sidebarLayout agentDisplayName={agent.name} />
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center p-8 text-center text-sm text-gray-500">
                Configure a voice bundle on the Test Agent tab to start a test call.
              </div>
            )
          ) : canTalkVoiceAI ? (
            <div className="flex-1 min-h-0 flex flex-col">
              <div className="flex-1 min-h-0 flex flex-col border-b border-gray-200">
                <div className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1 shrink-0">
                  <Mic className="h-3 w-3" />
                  Transcript
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto px-4 pb-3 space-y-2">
                  {transcripts.length === 0 ? (
                    <p className="text-xs text-gray-400 text-center py-6">
                      {isConnected ? 'Listening… transcript will appear here.' : 'Start a call to see the conversation.'}
                    </p>
                  ) : (
                    transcripts.map((t, i) => (
                      <div
                        key={i}
                        className={`text-sm rounded-lg px-3 py-2 ${
                          t.role === 'user' ? 'bg-blue-50 text-blue-900 ml-2' : 'bg-gray-100 text-gray-800 mr-2'
                        }`}
                      >
                        <span className="text-[10px] uppercase font-semibold opacity-60 block mb-0.5">
                          {t.role === 'user' ? 'You' : 'Agent'}
                        </span>
                        {t.content}
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="shrink-0 flex flex-col items-center px-6 py-5 bg-gray-50 border-t border-gray-200">
                <VoiceOrb
                  variant="indigo"
                  connected={isConnected}
                  connecting={isConnecting}
                  activeSpeaker={activeSpeaker}
                  className="mb-4"
                />
                <button
                  type="button"
                  onClick={() => (isConnected ? void handleDisconnect() : void handleConnectVoiceAI())}
                  disabled={isConnecting}
                  className={`flex items-center justify-center w-12 h-12 rounded-full shadow-lg transition-colors ${
                    isConnected
                      ? 'bg-red-600 hover:bg-red-700 text-white'
                      : 'bg-gray-900 hover:bg-gray-800 text-white'
                  } disabled:opacity-60`}
                  aria-label={isConnected ? 'End call' : 'Start call'}
                >
                  {isConnecting ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : isConnected ? (
                    <PhoneOff className="h-5 w-5" />
                  ) : (
                    <Phone className="h-5 w-5" />
                  )}
                </button>
                <p className="mt-3 text-xs text-gray-500 text-center">{speakerHint}</p>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center p-8 text-center text-sm text-gray-500">
              Link a Voice AI integration and provider agent ID on the Voice AI Agent tab to start a call.
            </div>
          )}
        </div>
      </aside>
    </>
  )

  if (typeof document === 'undefined') return null
  return createPortal(panel, document.body)
}
