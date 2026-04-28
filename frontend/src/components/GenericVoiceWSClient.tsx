import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Mic,
  MicOff,
  Loader,
  AlertTriangle,
  ArrowUp,
  ArrowDown,
  Filter,
  ExternalLink,
  CheckCircle,
  Clock,
  Save,
  Trash2,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import Button from './Button'
import { apiClient } from '../lib/api'
import type { WSProtocolConfig, TranscriptEntry, ParsedWSMessage } from '../lib/wsProtocols'

// ----- Audio helpers ---------------------------------------------------

function resampleFloat32(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input
  const ratio = fromRate / toRate
  const len = Math.round(input.length / ratio)
  const out = new Float32Array(len)
  for (let i = 0; i < len; i++) {
    const srcIdx = i * ratio
    const lo = Math.floor(srcIdx)
    const hi = Math.min(lo + 1, input.length - 1)
    const t = srcIdx - lo
    out[i] = input[lo] * (1 - t) + input[hi] * t
  }
  return out
}

function float32ToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return out
}

function int16ArrayToBase64(int16: Int16Array): string {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin)
}

// RMS in normalized [0,1] range. Used as a cheap voice-activity detector so
// we don't reset the silence timer on every ambient-noise frame.
function rmsInt16(samples: Int16Array): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (let i = 0; i < samples.length; i++) {
    const v = samples[i] / 32768
    sum += v * v
  }
  return Math.sqrt(sum / samples.length)
}

function rmsFloat32(samples: Float32Array): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
  return Math.sqrt(sum / samples.length)
}

// Threshold roughly separates voice from ambient / mic self-noise. Tuned for
// a typical laptop mic; voiced frames usually sit >= 0.03, idle rooms <= 0.01.
const VAD_RMS_THRESHOLD = 0.015

function base64ToFloat32(b64: string): Float32Array {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  const int16 = new Int16Array(bytes.buffer)
  const out = new Float32Array(int16.length)
  for (let i = 0; i < int16.length; i++) out[i] = int16[i] / 32768
  return out
}

function encodeWav(samples: Int16Array, sampleRate: number): Blob {
  const byteRate = sampleRate * 2
  const blockAlign = 2
  const dataSize = samples.byteLength
  const buf = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buf)
  const writeStr = (off: number, s: string) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)) }
  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true)
  writeStr(36, 'data')
  view.setUint32(40, dataSize, true)
  new Uint8Array(buf, 44).set(new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength))
  return new Blob([buf], { type: 'audio/wav' })
}

// ----- Types -----------------------------------------------------------

interface WSMessageLog {
  id: number
  direction: 'sent' | 'received'
  timestamp: string
  parsed: ParsedWSMessage
  size: number
}

type LogEntry = { timestamp: string; message: string; type: 'user' | 'bot' | 'system' }

type EvalStatus = 'idle' | 'queued' | 'evaluating' | 'failed'

interface SavedSession {
  callShortId: string
  savedAt: string
  transcriptCount: number
  hasRecording: boolean
  sessionStartedAt?: string | null
  sessionEndedAt?: string | null
  evalStatus: EvalStatus
  evalError?: string
}

// ----- Component -------------------------------------------------------

interface GenericVoiceWSClientProps {
  websocketUrl: string
  protocol: WSProtocolConfig
  agentId?: string
  onSessionSaved?: () => void
}

export default function GenericVoiceWSClient({
  websocketUrl,
  protocol,
  agentId,
  onSessionSaved,
}: GenericVoiceWSClientProps) {
  // ---- UI state -------------------------------------------------------
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [transcriptEntries, setTranscriptEntries] = useState<TranscriptEntry[]>([])
  const [wsMessages, setWsMessages] = useState<WSMessageLog[]>([])
  const [showAudioMsgs, setShowAudioMsgs] = useState(false)
  const [activePanel, setActivePanel] = useState<'transcript' | 'messages' | 'log'>('transcript')
  const [sessionStartedAt, setSessionStartedAt] = useState<string | null>(null)
  const [sessionEndedAt, setSessionEndedAt] = useState<string | null>(null)
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null)
  const [isSavingSession, setIsSavingSession] = useState(false)
  const [savedSessions, setSavedSessions] = useState<SavedSession[]>([])
  // Tracks whether the CURRENT (unsaved) transcript has already been saved,
  // so the primary button can show "Saved" / disable correctly. This resets
  // each time a new call is started.
  const [currentSavedId, setCurrentSavedId] = useState<string | null>(null)
  const navigate = useNavigate()

  // ---- Refs -----------------------------------------------------------
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null)
  const accBufRef = useRef<Float32Array>(new Float32Array(0))
  const playTimeRef = useRef(0)
  const recordDestRef = useRef<MediaStreamAudioDestinationNode | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const recordedChunksRef = useRef<Blob[]>([])
  const connectingRef = useRef(false)
  // Auto-save orchestration. When a session ends we want to save it only
  // once, and only after all post-disconnect async work (STT flushes + the
  // MediaRecorder's final onstop) has settled.
  const autoSaveRequestedRef = useRef(false)
  const recordingPendingRef = useRef(false)
  const msgIdRef = useRef(0)
  const logsEndRef = useRef<HTMLDivElement | null>(null)
  const transcriptEndRef = useRef<HTMLDivElement | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  const protocolRef = useRef(protocol)
  protocolRef.current = protocol

  // ---- STT state & refs ------------------------------------------------
  const [sttEnabled, setSttEnabled] = useState(false)
  const [pendingTranscriptions, setPendingTranscriptions] = useState(0)
  const userAudioBufRef = useRef<Int16Array[]>([])
  const agentAudioBufRef = useRef<Int16Array[]>([])
  const userSilenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const agentSilenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // A "turn" starts the moment voiced audio is detected and ends when the
  // silence timer fires. Silent frames received inside an active turn are
  // still buffered (so within-sentence pauses survive); silent frames outside
  // a turn are dropped entirely.
  const userTurnActiveRef = useRef(false)
  const agentTurnActiveRef = useRef(false)
  const sttEnabledRef = useRef(false)
  sttEnabledRef.current = sttEnabled

  const { data: sttConfig } = useQuery<{ available: boolean; provider?: string; model?: string; reason?: string }>({
    queryKey: ['agent-stt-config', agentId],
    queryFn: () => (agentId ? apiClient.getAgentSttConfig(agentId) : Promise.resolve({ available: false })),
    enabled: !!agentId,
    staleTime: 60_000,
  })


  const { data: s3Status } = useQuery({
    queryKey: ['s3-status'],
    queryFn: () => apiClient.getS3Status(),
    staleTime: 60_000,
  })

  // ---- Logging helpers ------------------------------------------------

  const log = useCallback((message: string, type: LogEntry['type'] = 'system') => {
    setLogs((prev) => [...prev.slice(-500), { timestamp: new Date().toISOString(), message, type }])
  }, [])

  const pushWsMessage = useCallback((direction: 'sent' | 'received', parsed: ParsedWSMessage, size: number) => {
    setWsMessages((prev) => [
      ...prev.slice(-500),
      { id: ++msgIdRef.current, direction, timestamp: new Date().toISOString(), parsed, size },
    ])
  }, [])

  // ---- STT flush helpers (dual-channel, independent) ---------------------

  const flushChannelBuffer = useCallback(
    (channel: 'user' | 'agent') => {
      const buf = channel === 'user' ? userAudioBufRef.current : agentAudioBufRef.current
      if (buf.length === 0) return

      const totalLen = buf.reduce((s, a) => s + a.length, 0)
      if (totalLen < 800) {
        if (channel === 'user') userAudioBufRef.current = []
        else agentAudioBufRef.current = []
        return
      }

      const merged = new Int16Array(totalLen)
      let off = 0
      for (const chunk of buf) { merged.set(chunk, off); off += chunk.length }
      if (channel === 'user') {
        userAudioBufRef.current = []
        userTurnActiveRef.current = false
      } else {
        agentAudioBufRef.current = []
        agentTurnActiveRef.current = false
      }

      if (!agentId) return

      const wavBlob = encodeWav(merged, protocolRef.current.sampleRate)
      setPendingTranscriptions((n) => n + 1)
      const durationSec = (totalLen / protocolRef.current.sampleRate).toFixed(1)
      log(`Transcribing ${channel} turn (${durationSec}s)...`, 'system')

      apiClient.transcribeTurn(agentId, channel, wavBlob)
        .then((res) => {
          const text = (res.transcript || '').trim()
          if (text) {
            const entry: TranscriptEntry = {
              role: channel === 'user' ? 'user' : 'agent',
              content: text,
              timestamp: new Date().toISOString(),
            }
            setTranscriptEntries((prev) => [...prev, entry])
            log(`${channel === 'user' ? 'User' : 'Agent'} (STT): ${text}`, channel === 'user' ? 'user' : 'bot')
          }
        })
        .catch((err: any) => {
          log(`STT failed for ${channel}: ${err?.response?.data?.detail || err?.message || 'unknown error'}`, 'system')
        })
        .finally(() => setPendingTranscriptions((n) => Math.max(0, n - 1)))
    },
    [agentId, log],
  )

  const flushChannelRef = useRef(flushChannelBuffer)
  flushChannelRef.current = flushChannelBuffer

  const resetUserSilenceTimer = useCallback(() => {
    if (userSilenceTimerRef.current) clearTimeout(userSilenceTimerRef.current)
    userSilenceTimerRef.current = setTimeout(() => {
      if (sttEnabledRef.current) flushChannelRef.current('user')
    }, 2000)
  }, [])

  const resetAgentSilenceTimer = useCallback(() => {
    if (agentSilenceTimerRef.current) clearTimeout(agentSilenceTimerRef.current)
    agentSilenceTimerRef.current = setTimeout(() => {
      if (sttEnabledRef.current) flushChannelRef.current('agent')
    }, 1500)
  }, [])

  // auto-scroll panels
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcriptEntries])
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [wsMessages])

  // ---- Audio playback -------------------------------------------------

  const playAudioChunk = useCallback(
    (b64: string) => {
      const ctx = audioCtxRef.current
      if (!ctx || !b64) return
      try {
        const samples = base64ToFloat32(b64)
        if (samples.length === 0) return
        const buf = ctx.createBuffer(1, samples.length, protocolRef.current.sampleRate)
        buf.getChannelData(0).set(samples)
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.connect(ctx.destination)
        if (recordDestRef.current) {
          src.connect(recordDestRef.current)
        }

        const now = ctx.currentTime
        if (playTimeRef.current < now) playTimeRef.current = now
        src.start(playTimeRef.current)
        playTimeRef.current += buf.duration

        // STT: VAD-gated agent buffering. See mic pipeline for rationale.
        if (sttEnabledRef.current) {
          const energy = rmsFloat32(samples)
          const voiced = energy > VAD_RMS_THRESHOLD
          const pcm16 = float32ToInt16(samples)
          if (voiced) {
            if (!agentTurnActiveRef.current) {
              agentTurnActiveRef.current = true
              log('Agent turn started', 'system')
            }
            agentAudioBufRef.current.push(pcm16)
            resetAgentSilenceTimer()
          } else if (agentTurnActiveRef.current) {
            agentAudioBufRef.current.push(pcm16)
          }
        }
      } catch {
        // ignore decode errors on individual chunks
      }
    },
    [resetAgentSilenceTimer],
  )

  // ---- WebSocket message handler --------------------------------------

  const handleWsMessage = useCallback(
    (event: MessageEvent) => {
      const data = event.data
      const size = typeof data === 'string' ? data.length : (data as ArrayBuffer).byteLength
      const parsed = protocolRef.current.parseMessage(data)

      pushWsMessage('received', parsed, size)

      if (parsed.responseMessage) {
        wsRef.current?.send(parsed.responseMessage)
      }

      if (parsed.type === 'audio' && parsed.audioBase64) {
        playAudioChunk(parsed.audioBase64)
      }

      if (parsed.type === 'transcript' && parsed.transcript) {
        const entry = parsed.transcript
        setTranscriptEntries((prev) => [...prev, entry])
        log(`${entry.role === 'user' ? 'User' : 'Agent'}: ${entry.content}`, entry.role === 'user' ? 'user' : 'bot')
      }

      if (parsed.type === 'control') {
        const t = parsed.raw?.type
        if (t) log(`Control: ${t}`, 'system')
      }
    },
    [log, pushWsMessage, playAudioChunk],
  )

  // ---- Mic capture + send pipeline -----------------------------------

  const startMicCapture = useCallback(() => {
    const ctx = audioCtxRef.current
    const stream = micStreamRef.current
    if (!ctx || !stream) return

    const source = ctx.createMediaStreamSource(stream)
    const processor = ctx.createScriptProcessor(4096, 1, 1)

    const targetRate = protocolRef.current.sampleRate
    const chunkSamples = Math.round(targetRate * protocolRef.current.sendIntervalMs / 1000)

    processor.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
      const raw = e.inputBuffer.getChannelData(0)
      const resampled = resampleFloat32(raw, ctx.sampleRate, targetRate)
      const prev = accBufRef.current
      const merged = new Float32Array(prev.length + resampled.length)
      merged.set(prev)
      merged.set(resampled, prev.length)

      let offset = 0
      while (offset + chunkSamples <= merged.length) {
        const chunk = merged.slice(offset, offset + chunkSamples)
        offset += chunkSamples
        const pcm16 = float32ToInt16(chunk)
        const b64 = int16ArrayToBase64(pcm16)
        const frame = protocolRef.current.wrapAudioFrame(b64)
        try {
          wsRef.current.send(frame)
        } catch {
          break
        }

        // VAD-gated STT buffering. Only voiced frames start/continue a turn
        // and reset the silence timer; silent frames outside a turn are
        // dropped so the timer can actually expire and flush the turn.
        if (sttEnabledRef.current) {
          const energy = rmsInt16(pcm16)
          const voiced = energy > VAD_RMS_THRESHOLD
          if (voiced) {
            if (!userTurnActiveRef.current) {
              userTurnActiveRef.current = true
              log('User turn started', 'system')
            }
            userAudioBufRef.current.push(pcm16)
            resetUserSilenceTimer()
          } else if (userTurnActiveRef.current) {
            // keep natural pauses inside an active turn
            userAudioBufRef.current.push(pcm16)
          }
        }
      }
      accBufRef.current = merged.slice(offset)
    }

    // Connect processor through a silent gain so it fires but doesn't
    // route mic audio to speakers.
    const silentGain = ctx.createGain()
    silentGain.gain.value = 0
    source.connect(processor)
    processor.connect(silentGain)
    silentGain.connect(ctx.destination)

    // Route mic into the recording destination so both sides are captured
    if (recordDestRef.current) {
      source.connect(recordDestRef.current)
    }

    scriptNodeRef.current = processor
  }, [])

  // ---- MediaRecorder for session recording ----------------------------

  const startRecording = useCallback(() => {
    if (mediaRecorderRef.current || typeof MediaRecorder === 'undefined') return
    // Prefer the mixed destination (mic + bot audio). Fall back to mic-only.
    const stream = recordDestRef.current?.stream || micStreamRef.current
    if (!stream) return
    try {
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const recorder = new MediaRecorder(stream, { mimeType })
      recordedChunksRef.current = []
      recorder.ondataavailable = (ev: BlobEvent) => {
        if (ev.data.size > 0) recordedChunksRef.current.push(ev.data)
      }
      recorder.onstop = () => {
        if (recordedChunksRef.current.length > 0) {
          setRecordedBlob(new Blob(recordedChunksRef.current, { type: recorder.mimeType || 'audio/webm' }))
        }
        recordingPendingRef.current = false
      }
      recorder.start(1000)
      mediaRecorderRef.current = recorder
      recordingPendingRef.current = true
      const isMixed = !!recordDestRef.current
      log(`Recording started (${isMixed ? 'mic + agent audio' : 'mic only'})`, 'system')
    } catch (err: any) {
      log(`Recording failed: ${err?.message || err}`, 'system')
    }
  }, [log])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    mediaRecorderRef.current = null
  }, [])

  // ---- Connect / disconnect ------------------------------------------

  const cleanupConnection = useCallback(
    (userInitiated: boolean) => {
      // Flush BOTH STT channel buffers on disconnect
      if (userSilenceTimerRef.current) { clearTimeout(userSilenceTimerRef.current); userSilenceTimerRef.current = null }
      if (agentSilenceTimerRef.current) { clearTimeout(agentSilenceTimerRef.current); agentSilenceTimerRef.current = null }
      if (sttEnabledRef.current) {
        flushChannelBuffer('user')
        flushChannelBuffer('agent')
      }
      userAudioBufRef.current = []
      agentAudioBufRef.current = []
      userTurnActiveRef.current = false
      agentTurnActiveRef.current = false

      stopRecording()
      if (scriptNodeRef.current) {
        scriptNodeRef.current.disconnect()
        scriptNodeRef.current = null
      }
      if (wsRef.current) {
        const ws = wsRef.current
        wsRef.current = null
        ws.onmessage = null
        ws.onclose = null
        ws.onerror = null
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
      }
      recordDestRef.current = null
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close().catch(() => {})
        audioCtxRef.current = null
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((t) => t.stop())
        micStreamRef.current = null
      }
      setIsConnected(false)
      setIsConnecting(false)
      setSessionEndedAt(new Date().toISOString())
      // Ask the auto-save effect to persist the session once all pending
      // work settles (STT flushes + recorder onstop). If there are no
      // transcripts, the effect will no-op.
      autoSaveRequestedRef.current = true
      if (userInitiated) log('Disconnected')
    },
    [stopRecording, log, flushChannelBuffer],
  )

  const disconnect = useCallback(() => {
    cleanupConnection(true)
  }, [cleanupConnection])

  const connect = useCallback(async () => {
    if (connectingRef.current) return
    connectingRef.current = true
    setIsConnecting(true)
    setError(null)
    log('Connecting...')

    // Reset previous session state (keep the savedSessions list so users can
    // still see and act on sessions saved earlier in this component's lifetime)
    setCurrentSavedId(null)
    autoSaveRequestedRef.current = false
    recordingPendingRef.current = false
    setRecordedBlob(null)
    setTranscriptEntries([])
    setWsMessages([])
    setSessionStartedAt(new Date().toISOString())
    setSessionEndedAt(null)
    accBufRef.current = new Float32Array(0)
    playTimeRef.current = 0
    userAudioBufRef.current = []
    agentAudioBufRef.current = []
    userTurnActiveRef.current = false
    agentTurnActiveRef.current = false
    if (userSilenceTimerRef.current) { clearTimeout(userSilenceTimerRef.current); userSilenceTimerRef.current = null }
    if (agentSilenceTimerRef.current) { clearTimeout(agentSilenceTimerRef.current); agentSilenceTimerRef.current = null }

    try {
      // Mic
      try {
        micStreamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true })
        log('Microphone acquired')
      } catch {
        micStreamRef.current = null
        log('Microphone unavailable — connecting without mic', 'system')
      }

      // AudioContext + recording destination (mixes mic + bot audio)
      const ctx = new AudioContext({ sampleRate: 48000 })
      audioCtxRef.current = ctx
      if (ctx.state === 'suspended') await ctx.resume()
      recordDestRef.current = ctx.createMediaStreamDestination()

      // WebSocket
      log(`Opening WebSocket to ${websocketUrl}`)
      log(`Protocol: ${protocolRef.current.name} (${protocolRef.current.sampleRate / 1000} kHz, ${protocolRef.current.sendIntervalMs} ms)`)
      const ws = new WebSocket(websocketUrl)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      await new Promise<void>((resolve, reject) => {
        let settled = false
        const settle = (fn: () => void) => {
          if (!settled) { settled = true; fn() }
        }
        const timer = setTimeout(
          () => settle(() => reject(new Error(
            `Connection timed out after 15 s. The server at ${new URL(websocketUrl).host} did not respond to the WebSocket upgrade. ` +
            'This often means the agent restricts which origins can connect. ' +
            'Try creating your own agent (with open allowed-origins) or use a backend proxy.'
          ))),
          15000,
        )
        ws.onopen = () => { clearTimeout(timer); settle(() => resolve()) }
        ws.onerror = () => {
          clearTimeout(timer)
          settle(() => reject(new Error(
            `WebSocket connection to ${new URL(websocketUrl).host} failed. ` +
            'Check the URL, your network, and whether the agent allows connections from this origin.'
          )))
        }
        ws.onclose = (ev) => {
          clearTimeout(timer)
          settle(() => reject(new Error(
            `WebSocket closed before connecting (code ${ev.code}${ev.reason ? ': ' + ev.reason : ''}). ` +
            'The server may have rejected the connection — public agents often restrict allowed origins.'
          )))
        }
      })

      log('WebSocket upgrade successful (101)')

      // Send init messages
      const initMsgs = protocolRef.current.buildInitMessages?.() || []
      for (const msg of initMsgs) {
        ws.send(msg)
        const preview = msg.length > 140 ? msg.slice(0, 140) + '…' : msg
        log(`Sent init: ${preview}`)
      }
      if (initMsgs.length === 0) {
        log('No init messages for this protocol — waiting for server messages', 'system')
      }

      ws.onmessage = handleWsMessage
      ws.onclose = (ev) => {
        log(`WebSocket closed (code ${ev.code}${ev.reason ? `, ${ev.reason}` : ''})`)
        cleanupConnection(false)
      }
      ws.onerror = () => {
        log('WebSocket error')
      }

      // Start mic capture + recording
      if (micStreamRef.current) {
        startMicCapture()
      }
      startRecording()

      setIsConnected(true)
      setIsConnecting(false)
      log('Ready — streaming mic audio', 'system')
    } catch (err: any) {
      const msg = err?.message || 'Failed to connect'
      setError(msg)
      log(`Error: ${msg}`)
      cleanupConnection(false)
    } finally {
      connectingRef.current = false
      setIsConnecting(false)
    }
  }, [websocketUrl, handleWsMessage, log, startMicCapture, startRecording, cleanupConnection])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.onmessage = null
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
      if (scriptNodeRef.current) {
        scriptNodeRef.current.disconnect()
        scriptNodeRef.current = null
      }
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close().catch(() => {})
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((t) => t.stop())
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop()
      }
    }
  }, [])

  // ---- Save / Evaluate ------------------------------------------------

  const handleSaveSession = useCallback(async () => {
    if (!agentId || !websocketUrl || transcriptEntries.length === 0) return
    try {
      setIsSavingSession(true)
      setError(null)
      const audioFile = recordedBlob
        ? new File([recordedBlob], `custom-ws-${Date.now()}.webm`, { type: recordedBlob.type || 'audio/webm' })
        : undefined
      const res = await apiClient.createCustomWebsocketSession({
        agent_id: agentId,
        websocket_url: websocketUrl,
        transcript_entries: transcriptEntries,
        started_at: sessionStartedAt || undefined,
        ended_at: sessionEndedAt || new Date().toISOString(),
        audio_file: audioFile,
      })
      const newSession: SavedSession = {
        callShortId: res.call_short_id,
        savedAt: new Date().toISOString(),
        transcriptCount: transcriptEntries.length,
        hasRecording: !!recordedBlob,
        sessionStartedAt: sessionStartedAt,
        sessionEndedAt: sessionEndedAt || new Date().toISOString(),
        evalStatus: 'idle',
      }
      setSavedSessions((prev) => [newSession, ...prev])
      setCurrentSavedId(res.call_short_id)
      log(`Session saved as ${res.call_short_id}`, 'system')
      onSessionSaved?.()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to save session'
      setError(msg)
      log(`Save failed: ${msg}`, 'system')
    } finally {
      setIsSavingSession(false)
    }
  }, [
    agentId,
    websocketUrl,
    transcriptEntries,
    recordedBlob,
    sessionStartedAt,
    sessionEndedAt,
    log,
    onSessionSaved,
  ])

  // Auto-save the session once disconnect + all post-disconnect async work
  // have settled. Guarded so it fires at most once per connection.
  useEffect(() => {
    if (!autoSaveRequestedRef.current) return
    if (isConnected || isConnecting) return
    if (pendingTranscriptions > 0) return
    if (recordingPendingRef.current) return
    if (isSavingSession) return
    if (currentSavedId) return
    if (!agentId) return
    if (transcriptEntries.length === 0) {
      // Nothing worth saving — clear the request so we don't retrigger.
      autoSaveRequestedRef.current = false
      return
    }
    autoSaveRequestedRef.current = false
    handleSaveSession()
  }, [
    isConnected,
    isConnecting,
    pendingTranscriptions,
    recordedBlob,
    transcriptEntries,
    isSavingSession,
    currentSavedId,
    agentId,
    handleSaveSession,
  ])

  const updateSession = (callShortId: string, patch: Partial<SavedSession>) => {
    setSavedSessions((prev) =>
      prev.map((s) => (s.callShortId === callShortId ? { ...s, ...patch } : s)),
    )
  }

  const handleEvaluateSession = async (callShortId: string) => {
    updateSession(callShortId, { evalStatus: 'evaluating', evalError: undefined })
    try {
      await apiClient.evaluateCustomWebsocketSession(callShortId)
      updateSession(callShortId, { evalStatus: 'queued' })
      log(`Evaluation queued for ${callShortId}`, 'system')
      onSessionSaved?.()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Evaluation failed'
      updateSession(callShortId, { evalStatus: 'failed', evalError: msg })
      log(`Evaluation failed: ${msg}`, 'system')
    }
  }

  const handleOpenSession = (callShortId: string) => {
    navigate(`/playground/call-recordings/${callShortId}`)
  }

  const handleRemoveSession = (callShortId: string) => {
    setSavedSessions((prev) => prev.filter((s) => s.callShortId !== callShortId))
    if (currentSavedId === callShortId) setCurrentSavedId(null)
  }

  // ---- Filtered messages for display ----------------------------------

  const visibleMessages = showAudioMsgs ? wsMessages : wsMessages.filter((m) => m.parsed.type !== 'audio')

  // ---- Render ---------------------------------------------------------

  const panelClasses = (panel: string) =>
    `px-3 py-2 text-xs font-medium cursor-pointer transition-colors ${
      activePanel === panel
        ? 'border-b-2 border-yellow-500 text-yellow-700'
        : 'text-gray-500 hover:text-gray-700'
    }`

  return (
    <div className="space-y-4">
      <div className="bg-white shadow rounded-lg p-5">
        {/* Header */}
        <div className="mb-3">
          <h3 className="text-sm font-semibold text-gray-900">
            {protocol.name}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5 font-mono truncate">{websocketUrl}</p>
          <p className="text-xs text-gray-400 mt-0.5">{protocol.description}</p>
        </div>

        {/* Warnings */}
        {s3Status && !s3Status.enabled && (
          <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3 text-xs">
            <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-amber-800">Storage not configured</p>
              <p className="text-amber-700">Audio recordings will not be saved. Transcripts will still be captured.</p>
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-3">
            <p className="text-xs text-red-800">{error}</p>
          </div>
        )}

        {/* STT toggle */}
        {agentId && sttConfig && sttConfig.available && (
          <div className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg p-3 mb-3">
            <div className="flex items-center gap-2">
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={sttEnabled}
                  onChange={(e) => setSttEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-gray-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600 peer-disabled:opacity-50" />
              </label>
              <span className="text-sm font-medium text-gray-700">Live Transcription</span>
              {sttConfig.provider && (
                <span className="text-[10px] px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded font-mono">
                  {sttConfig.provider}{sttConfig.model ? ` · ${sttConfig.model}` : ''}
                </span>
              )}
              {pendingTranscriptions > 0 && (
                <Loader className="h-3.5 w-3.5 text-indigo-500 animate-spin" />
              )}
            </div>
            {sttEnabled && pendingTranscriptions > 0 && (
              <span className="text-[10px] text-gray-400">Transcribing...</span>
            )}
          </div>
        )}
        {!agentId && (
          <div className="text-xs text-amber-500 mb-3 px-1">
            Select an agent to enable live transcription (STT).
          </div>
        )}
        {agentId && sttConfig && !sttConfig.available && (
          <div className="text-xs text-amber-500 mb-3 px-1">
            Live transcription unavailable: {sttConfig.reason || 'No STT provider configured in voice bundle'}
          </div>
        )}

        {/* Status + controls */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {isConnected ? (
              <>
                <div className="w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse" />
                <span className="text-sm font-medium text-gray-700">Connected</span>
                <span className="text-xs text-gray-400">
                  {protocol.sampleRate / 1000} kHz &middot; {protocol.sendIntervalMs} ms frames
                </span>
                {sttEnabled && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-green-100 text-green-700 rounded">STT ON</span>
                )}
              </>
            ) : (
              <span className="text-sm text-gray-500">{isConnecting ? 'Connecting...' : 'Disconnected'}</span>
            )}
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
              <Button onClick={disconnect} variant="danger" leftIcon={<MicOff className="h-4 w-4" />}>
                Disconnect
              </Button>
            )}
          </div>
        </div>

        {/* Panel tabs */}
        <div className="flex border-b border-gray-200 mb-2">
          <button className={panelClasses('transcript')} onClick={() => setActivePanel('transcript')}>
            Transcript {transcriptEntries.length > 0 && `(${transcriptEntries.length})`}
          </button>
          <button className={panelClasses('messages')} onClick={() => setActivePanel('messages')}>
            Messages {wsMessages.length > 0 && `(${wsMessages.length})`}
          </button>
          <button className={panelClasses('log')} onClick={() => setActivePanel('log')}>
            Debug Log
          </button>
        </div>

        {/* Transcript panel */}
        {activePanel === 'transcript' && (
          <div className="h-72 overflow-y-auto bg-gray-50 rounded border border-gray-200 p-4">
            {transcriptEntries.length === 0 ? (
              <p className="text-gray-400 text-center text-xs py-12">
                No transcript yet. Connect and start speaking.
              </p>
            ) : (
              <div className="space-y-3">
                {transcriptEntries.map((e, i) => {
                  const ts = new Date(e.timestamp)
                  const elapsed = sessionStartedAt
                    ? Math.max(0, Math.round((ts.getTime() - new Date(sessionStartedAt).getTime()) / 1000))
                    : null
                  const elapsedStr = elapsed !== null
                    ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`
                    : null
                  return (
                    <div key={i} className={`flex ${e.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                        e.role === 'user'
                          ? 'bg-indigo-600 text-white rounded-br-none'
                          : 'bg-white border border-gray-200 text-gray-800 rounded-bl-none'
                      }`}>
                        <div className={`flex items-center gap-2 mb-0.5 ${
                          e.role === 'user' ? 'opacity-70' : ''
                        }`}>
                          <span className={`text-[10px] font-semibold uppercase tracking-wider ${
                            e.role === 'user' ? '' : 'text-gray-400'
                          }`}>
                            {e.role === 'user' ? 'You' : 'Agent'}
                          </span>
                          <span className={`text-[10px] ${
                            e.role === 'user' ? 'opacity-70' : 'text-gray-300'
                          }`}>
                            {elapsedStr && <span className="mr-1">[{elapsedStr}]</span>}
                            {ts.toLocaleTimeString()}
                          </span>
                        </div>
                        <p className="text-sm leading-relaxed">{e.content}</p>
                      </div>
                    </div>
                  )
                })}
                <div ref={transcriptEndRef} />
              </div>
            )}
          </div>
        )}

        {/* Messages panel */}
        {activePanel === 'messages' && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <button
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                onClick={() => setShowAudioMsgs((v) => !v)}
              >
                <Filter className="h-3 w-3" />
                {showAudioMsgs ? 'Hide audio frames' : 'Show audio frames'}
              </button>
              <span className="text-xs text-gray-400">
                {visibleMessages.length} / {wsMessages.length} messages
              </span>
            </div>
            <div className="h-72 overflow-y-auto bg-gray-50 rounded border border-gray-200 p-2 font-mono text-xs">
              {visibleMessages.length === 0 ? (
                <p className="text-gray-400 text-center py-12">No messages yet.</p>
              ) : (
                <div className="space-y-1">
                  {visibleMessages.map((m) => (
                    <div key={m.id} className="flex gap-1.5 items-start">
                      {m.direction === 'sent' ? (
                        <ArrowUp className="h-3 w-3 text-blue-400 flex-shrink-0 mt-0.5" />
                      ) : (
                        <ArrowDown className="h-3 w-3 text-green-400 flex-shrink-0 mt-0.5" />
                      )}
                      <span className="text-gray-400 flex-shrink-0">
                        {new Date(m.timestamp).toLocaleTimeString()}
                      </span>
                      <span
                        className={`px-1 rounded text-[10px] flex-shrink-0 ${
                          m.parsed.type === 'audio'
                            ? 'bg-purple-100 text-purple-700'
                            : m.parsed.type === 'transcript'
                              ? 'bg-green-100 text-green-700'
                              : m.parsed.type === 'ping'
                                ? 'bg-yellow-100 text-yellow-700'
                                : m.parsed.type === 'control'
                                  ? 'bg-blue-100 text-blue-700'
                                  : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {m.parsed.type}
                      </span>
                      <span className="text-gray-600 break-all">
                        {m.parsed.type === 'audio'
                          ? `[${m.size} bytes]`
                          : typeof m.parsed.raw === 'string'
                            ? m.parsed.raw.slice(0, 200)
                            : JSON.stringify(m.parsed.raw).slice(0, 200)}
                      </span>
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Debug log panel */}
        {activePanel === 'log' && (
          <div className="h-72 overflow-y-auto bg-gray-50 rounded border border-gray-200 p-3 font-mono text-xs">
            {logs.length === 0 ? (
              <p className="text-gray-400 text-center py-12">No logs yet. Connect to start.</p>
            ) : (
              <>
                {logs.map((entry, idx) => (
                  <div
                    key={idx}
                    className={`mb-0.5 ${
                      entry.type === 'user'
                        ? 'text-blue-600'
                        : entry.type === 'bot'
                          ? 'text-green-600'
                          : 'text-gray-600'
                    }`}
                  >
                    <span className="text-gray-400">{new Date(entry.timestamp).toLocaleTimeString()}</span>{' '}
                    {entry.message}
                  </div>
                ))}
                <div ref={logsEndRef} />
              </>
            )}
          </div>
        )}

        {/* Saved sessions */}
        {(savedSessions.length > 0 || (!isConnected && transcriptEntries.length > 0)) && (
          <div className="mt-4 rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                  <Save className="h-4 w-4 text-indigo-600" />
                  Saved Test Sessions
                  {savedSessions.length > 0 && (
                    <span className="text-[10px] font-medium text-gray-500 bg-gray-100 rounded-full px-2 py-0.5">
                      {savedSessions.length}
                    </span>
                  )}
                </h3>
                <p className="mt-1 text-xs text-gray-600">
                  Sessions are saved automatically when you disconnect.
                </p>
              </div>
              {/* Inline auto-save status (replaces the old manual button) */}
              {!isConnected && transcriptEntries.length > 0 && (
                <div className="flex-shrink-0">
                  {isSavingSession ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-full px-2.5 py-1">
                      <Loader className="h-3 w-3 animate-spin" />
                      Saving session…
                    </span>
                  ) : currentSavedId ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-green-700 bg-green-50 border border-green-100 rounded-full px-2.5 py-1">
                      <CheckCircle className="h-3 w-3" />
                      Session saved
                    </span>
                  ) : !agentId ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-full px-2.5 py-1">
                      <AlertTriangle className="h-3 w-3" />
                      Select an agent to enable auto-save
                    </span>
                  ) : pendingTranscriptions > 0 ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-full px-2.5 py-1">
                      <Loader className="h-3 w-3 animate-spin" />
                      Finishing transcription…
                    </span>
                  ) : null}
                </div>
              )}
            </div>


            {savedSessions.length === 0 ? (
              <div className="mt-3 rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-6 text-center text-xs text-gray-500">
                No saved sessions yet. End the call and click <span className="font-medium">Save Session</span> to save this transcript.
              </div>
            ) : (
              <ul className="mt-3 divide-y divide-gray-100 rounded-md border border-gray-200 bg-white overflow-hidden">
                {savedSessions.map((s) => (
                  <li key={s.callShortId} className="p-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 hover:bg-gray-50 transition-colors">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <button
                          type="button"
                          onClick={() => handleOpenSession(s.callShortId)}
                          className="font-mono text-sm font-semibold text-indigo-600 hover:text-indigo-700 hover:underline truncate"
                          title="Open call details"
                        >
                          {s.callShortId}
                        </button>
                        {s.callShortId === currentSavedId && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">
                            just saved
                          </span>
                        )}
                        {s.evalStatus === 'queued' && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                            eval queued
                          </span>
                        )}
                        {s.evalStatus === 'evaluating' && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium inline-flex items-center gap-1">
                            <Loader className="h-2.5 w-2.5 animate-spin" />
                            queuing
                          </span>
                        )}
                        {s.evalStatus === 'failed' && (
                          <span
                            className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 font-medium"
                            title={s.evalError || 'Evaluation failed'}
                          >
                            eval failed
                          </span>
                        )}
                        {s.hasRecording && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 font-medium">
                            with recording
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-3 text-[11px] text-gray-500 flex-wrap">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {new Date(s.savedAt).toLocaleTimeString()}
                        </span>
                        <span>{s.transcriptCount} turn{s.transcriptCount === 1 ? '' : 's'}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      {s.evalStatus !== 'queued' && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleEvaluateSession(s.callShortId)}
                          isLoading={s.evalStatus === 'evaluating'}
                          disabled={s.evalStatus === 'evaluating'}
                        >
                          {s.evalStatus === 'failed' ? 'Retry Evaluation' : 'Run Evaluation'}
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleOpenSession(s.callShortId)}
                        leftIcon={<ExternalLink className="h-3.5 w-3.5" />}
                      >
                        Open
                      </Button>
                      <button
                        type="button"
                        onClick={() => handleRemoveSession(s.callShortId)}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                        title="Remove from list"
                        aria-label="Remove from list"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
