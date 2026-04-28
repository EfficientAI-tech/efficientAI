export type AudioEncoding = 'pcm16-base64' | 'pcm16-binary'

export interface TranscriptEntry {
  role: 'user' | 'agent'
  content: string
  timestamp: string
}

export interface ParsedWSMessage {
  type: 'audio' | 'transcript' | 'control' | 'ping' | 'unknown'
  audioBase64?: string
  transcript?: TranscriptEntry
  /** Auto-response to send back (e.g. pong for ping) */
  responseMessage?: string
  raw: any
  rawString?: string
}

export interface WSProtocolConfig {
  id: string
  name: string
  description: string
  urlPlaceholder?: string
  /** Messages to send immediately after WebSocket opens */
  buildInitMessages?: () => string[]
  audioEncoding: AudioEncoding
  sampleRate: number
  /** How often (ms) to flush accumulated mic audio as one frame */
  sendIntervalMs: number
  /** Wrap base64-encoded PCM audio into a sendable WS text frame */
  wrapAudioFrame: (base64Audio: string) => string
  /** Parse an incoming WS message into a structured form */
  parseMessage: (data: string | ArrayBuffer) => ParsedWSMessage
}

// ----- helpers --------------------------------------------------------

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}

// =====================================================================
//  Generic protocol – fully configurable baseline
// =====================================================================

const genericProtocol: WSProtocolConfig = {
  id: 'generic',
  name: 'Generic WebSocket',
  description:
    'Raw WebSocket connection with configurable audio format. Sends JSON messages with base64 PCM audio and displays all received messages in the inspector.',
  urlPlaceholder: 'wss://your-voice-agent.example.com/ws',
  audioEncoding: 'pcm16-base64',
  sampleRate: 16000,
  sendIntervalMs: 100,

  wrapAudioFrame: (base64Audio) => JSON.stringify({ audio: base64Audio }),

  parseMessage: (data): ParsedWSMessage => {
    if (data instanceof ArrayBuffer) {
      return { type: 'audio', audioBase64: arrayBufferToBase64(data), raw: `[binary ${data.byteLength} bytes]` }
    }
    try {
      const msg = JSON.parse(data as string)

      // Audio: look for common field names
      const b64 = msg.audio_base_64 || msg.audio || msg.audioData || msg.delta
      if (b64 && typeof b64 === 'string' && b64.length > 100) {
        return { type: 'audio', audioBase64: b64, raw: msg }
      }

      // Transcript: { type: "transcript", role: "user"|"agent", content: "..." }
      if (msg.type === 'transcript' && msg.content && (msg.role === 'user' || msg.role === 'agent')) {
        return {
          type: 'transcript',
          transcript: { role: msg.role, content: msg.content, timestamp: new Date().toISOString() },
          raw: msg,
        }
      }

      return { type: 'unknown', raw: msg, rawString: data as string }
    } catch {
      return { type: 'unknown', raw: data, rawString: data as string }
    }
  },
}

// =====================================================================
//  Registry
// =====================================================================

export const WS_PROTOCOLS: WSProtocolConfig[] = [
  genericProtocol,
]

export function getProtocolById(id: string): WSProtocolConfig {
  return WS_PROTOCOLS.find((p) => p.id === id) || genericProtocol
}
