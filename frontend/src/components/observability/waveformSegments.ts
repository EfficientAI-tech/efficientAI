import type { ObservabilityCallData } from '../../types/api'

export type WaveformSpeaker = 'agent' | 'user'

export interface WaveformSegment {
  speaker: WaveformSpeaker
  startSec: number
  endSec: number
  text?: string
}

interface RawSegment {
  speaker?: string
  role?: string
  text?: string
  content?: string
  start?: number
  end?: number
  start_time?: number
  end_time?: number
}

function normalizeSpeaker(raw: string | undefined, role?: string): WaveformSpeaker {
  const value = (raw || role || '').toLowerCase()
  if (
    value === 'user' ||
    value === 'caller' ||
    value === 'customer' ||
    value === 'speaker 1' ||
    value === 'speaker_1'
  ) {
    return 'user'
  }
  return 'agent'
}

function toSeconds(value: number | undefined): number | null {
  if (value === undefined || value === null || Number.isNaN(value)) return null
  if (value > 1e10) return value / 1000
  return value
}

export function buildWaveformSegments(
  callData: ObservabilityCallData | null | undefined,
  transcriptTurns: Array<{ role: 'user' | 'agent'; content: string; start_time?: number }>,
  _fallbackDurationSec?: number | null,
): WaveformSegment[] {
  const raw = callData?.speaker_segments
  if (Array.isArray(raw) && raw.length > 0) {
    return (raw as RawSegment[])
      .map((seg, index) => {
        const startSec = toSeconds(seg.start ?? seg.start_time) ?? index * 2
        const endSec = toSeconds(seg.end ?? seg.end_time) ?? startSec + 1.5
        return {
          speaker: normalizeSpeaker(seg.speaker, seg.role),
          startSec: Math.max(0, startSec),
          endSec: Math.max(startSec + 0.2, endSec),
          text: seg.text || seg.content,
        }
      })
      .sort((a, b) => a.startSec - b.startSec)
  }

  let elapsed = 0
  return transcriptTurns.map((turn) => {
    const startSec =
      turn.start_time !== undefined ? (toSeconds(turn.start_time) ?? elapsed) : elapsed
    const wordCount = turn.content.split(/\s+/).filter(Boolean).length
    const duration = Math.max(1.2, wordCount * 0.35)
    const endSec = startSec + duration
    elapsed = endSec
    return {
      speaker: turn.role === 'user' ? 'user' : 'agent',
      startSec,
      endSec,
      text: turn.content,
    }
  })
}

export function findSegmentIndexAtTime(segments: WaveformSegment[], timeSec: number): number | null {
  const idx = segments.findIndex((seg) => timeSec >= seg.startSec && timeSec <= seg.endSec + 0.05)
  if (idx >= 0) return idx
  let nearest = 0
  let nearestDist = Infinity
  segments.forEach((seg, i) => {
    const dist = Math.min(Math.abs(timeSec - seg.startSec), Math.abs(timeSec - seg.endSec))
    if (dist < nearestDist) {
      nearest = i
      nearestDist = dist
    }
  })
  return segments.length > 0 ? nearest : null
}

export function mapTranscriptIndexToSegmentIndex(
  transcriptTurns: Array<{ role: 'user' | 'agent'; content: string; start_time?: number }>,
  segments: WaveformSegment[],
  transcriptIndex: number,
): number | null {
  if (segments.length === 0 || transcriptIndex < 0) return null
  const turn = transcriptTurns[transcriptIndex]
  if (!turn) return null
  const turnStart =
    turn.start_time !== undefined ? (toSeconds(turn.start_time) ?? null) : null
  if (turnStart !== null) {
    const match = segments.findIndex(
      (seg) =>
        seg.speaker === (turn.role === 'user' ? 'user' : 'agent') &&
        Math.abs(seg.startSec - turnStart) < 1.5,
    )
    if (match >= 0) return match
  }
  const sameSpeakerSegments = segments
    .map((seg, i) => ({ seg, i }))
    .filter(({ seg }) => seg.speaker === (turn.role === 'user' ? 'user' : 'agent'))
  const speakerTurnIndex = transcriptTurns
    .slice(0, transcriptIndex + 1)
    .filter((t) => t.role === turn.role).length - 1
  return sameSpeakerSegments[speakerTurnIndex]?.i ?? null
}
