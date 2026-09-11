import { apiClient } from './api'
import { getVapiRecordingTracks } from './recordingUrls'

export interface CachedWaveformTrack {
  label: string
  color: string
  mutedColor: string
  peaks: Float32Array
}

export interface CachedWaveform {
  tracks: CachedWaveformTrack[]
  duration: number
}

const MAX_CACHE_ENTRIES = 10
const MAX_RAW_AUDIO_ENTRIES = 12
const waveformCache = new Map<string, CachedWaveform>()
const rawAudioCache = new Map<string, ArrayBuffer>()
const playbackBlobUrls = new Map<string, string>()
const playbackBlobRefCounts = new Map<string, number>()
const inflightFetches = new Map<string, Promise<ArrayBuffer | null>>()

export function playbackKeyForCall(callShortId: string, stereo: boolean): string {
  return `${callShortId}:${stereo ? 'stereo' : 'mono'}`
}

export function playbackKeyForObservability(callShortId: string): string {
  return `obs:${callShortId}`
}

export function playbackKeyForEvaluator(evaluatorResultId: string): string {
  return `eval:${evaluatorResultId}`
}

function guessAudioMimeType(arrayBuffer: ArrayBuffer): string {
  const bytes = new Uint8Array(arrayBuffer, 0, Math.min(12, arrayBuffer.byteLength))
  if (bytes.length >= 4 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46) {
    return 'audio/wav'
  }
  if (bytes.length >= 3 && bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33) {
    return 'audio/mpeg'
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0) {
    return 'audio/mpeg'
  }
  return 'audio/wav'
}

function revokePlaybackBlobUrl(key: string): void {
  const url = playbackBlobUrls.get(key)
  if (!url) return
  URL.revokeObjectURL(url)
  playbackBlobUrls.delete(key)
  playbackBlobRefCounts.delete(key)
}

export function retainPlaybackBlobUrl(key: string): void {
  playbackBlobRefCounts.set(key, (playbackBlobRefCounts.get(key) ?? 0) + 1)
}

export function releasePlaybackBlobUrl(key: string): void {
  const next = (playbackBlobRefCounts.get(key) ?? 0) - 1
  if (next <= 0) {
    playbackBlobRefCounts.delete(key)
    if (!rawAudioCache.has(key) && !waveformCache.has(key)) {
      revokePlaybackBlobUrl(key)
    }
  } else {
    playbackBlobRefCounts.set(key, next)
  }
}

function evictOldestMap<T>(
  map: Map<string, T>,
  max: number,
  onEvict?: (value: T, key: string) => void,
): void {
  while (map.size > max) {
    const oldestKey = map.keys().next().value
    if (!oldestKey) break
    const entry = map.get(oldestKey)
    if (entry !== undefined) onEvict?.(entry, oldestKey)
    map.delete(oldestKey)
    if ((playbackBlobRefCounts.get(oldestKey) ?? 0) <= 0) {
      revokePlaybackBlobUrl(oldestKey)
    }
  }
}

function evictOldestIfNeeded(): void {
  evictOldestMap(waveformCache, MAX_CACHE_ENTRIES)
}

function evictRawAudioIfNeeded(): void {
  evictOldestMap(rawAudioCache, MAX_RAW_AUDIO_ENTRIES)
}

function keysForCallShortId(callShortId: string): string[] {
  return [
    playbackKeyForCall(callShortId, false),
    playbackKeyForCall(callShortId, true),
  ]
}

export function clearCallRecordingAudioCache(callShortId: string): void {
  for (const key of keysForCallShortId(callShortId)) {
    waveformCache.delete(key)
    rawAudioCache.delete(key)
    inflightFetches.delete(key)
    if ((playbackBlobRefCounts.get(key) ?? 0) <= 0) {
      revokePlaybackBlobUrl(key)
    }
  }
}

export function clearObservabilityAudioCache(callShortId: string): void {
  const key = playbackKeyForObservability(callShortId)
  rawAudioCache.delete(key)
  inflightFetches.delete(key)
  if ((playbackBlobRefCounts.get(key) ?? 0) <= 0) {
    revokePlaybackBlobUrl(key)
  }
}

export function clearEvaluatorAudioCache(evaluatorResultId: string): void {
  const key = playbackKeyForEvaluator(evaluatorResultId)
  waveformCache.delete(key)
  rawAudioCache.delete(key)
  inflightFetches.delete(key)
  if ((playbackBlobRefCounts.get(key) ?? 0) <= 0) {
    revokePlaybackBlobUrl(key)
  }
}

export function getOrCreatePlaybackBlobUrl(key: string, arrayBuffer: ArrayBuffer): string {
  const existing = playbackBlobUrls.get(key)
  if (existing) return existing
  const url = URL.createObjectURL(
    new Blob([arrayBuffer.slice(0)], { type: guessAudioMimeType(arrayBuffer) }),
  )
  playbackBlobUrls.set(key, url)
  return url
}

export function getPlaybackBlobUrl(key: string): string | null {
  return playbackBlobUrls.get(key) ?? null
}

export function resolvePlaybackBlobUrl(key: string, arrayBuffer?: ArrayBuffer | null): string | null {
  if (arrayBuffer?.byteLength) {
    return getOrCreatePlaybackBlobUrl(key, arrayBuffer)
  }
  return getPlaybackBlobUrl(key)
}

export function getRawAudioBuffer(key: string): ArrayBuffer | null {
  const entry = rawAudioCache.get(key)
  if (!entry) return null
  rawAudioCache.delete(key)
  rawAudioCache.set(key, entry)
  return entry
}

export function preferStereoWaveform(
  callData: Record<string, unknown> | null | undefined,
  platform?: string | null,
): boolean {
  if ((platform || '').toLowerCase() !== 'vapi') return false
  return Boolean(getVapiRecordingTracks(callData).stereo)
}

export function getCachedWaveform(callShortId: string, stereo: boolean): CachedWaveform | null {
  const key = playbackKeyForCall(callShortId, stereo)
  const entry = waveformCache.get(key)
  if (!entry) return null
  waveformCache.delete(key)
  waveformCache.set(key, entry)
  return entry
}

export function setCachedWaveform(
  callShortId: string,
  stereo: boolean,
  entry: CachedWaveform,
): void {
  const key = playbackKeyForCall(callShortId, stereo)
  waveformCache.set(key, entry)
  evictOldestIfNeeded()
}

export async function fetchCallRecordingAudio(
  callShortId: string,
  stereo: boolean,
): Promise<ArrayBuffer | null> {
  const key = playbackKeyForCall(callShortId, stereo)
  const cached = getRawAudioBuffer(key)
  if (cached) return cached

  const inflight = inflightFetches.get(key)
  if (inflight) return inflight

  const promise = apiClient
    .getCallRecordingAudioBuffer(callShortId, { stereo })
    .then((buffer) => {
      if (buffer?.byteLength) {
        rawAudioCache.set(key, buffer)
        evictRawAudioIfNeeded()
      }
      return buffer
    })
    .catch(() => null)
    .finally(() => {
      inflightFetches.delete(key)
    })

  inflightFetches.set(key, promise)
  return promise
}

export function prefetchCallRecordingAudio(callShortId: string, stereo = false): void {
  const key = playbackKeyForCall(callShortId, stereo)
  if (waveformCache.has(key) || rawAudioCache.has(key) || inflightFetches.has(key)) return
  void fetchCallRecordingAudio(callShortId, stereo)
}

export async function fetchObservabilityCallAudio(callShortId: string): Promise<ArrayBuffer | null> {
  const key = playbackKeyForObservability(callShortId)
  const cached = getRawAudioBuffer(key)
  if (cached) return cached

  const inflight = inflightFetches.get(key)
  if (inflight) return inflight

  const promise = apiClient
    .getObservabilityCallAudioBuffer(callShortId)
    .then((buffer) => {
      if (buffer?.byteLength) {
        rawAudioCache.set(key, buffer)
        evictRawAudioIfNeeded()
      }
      return buffer
    })
    .catch(() => null)
    .finally(() => {
      inflightFetches.delete(key)
    })

  inflightFetches.set(key, promise)
  return promise
}

export function prefetchObservabilityCallAudio(callShortId: string): void {
  const key = playbackKeyForObservability(callShortId)
  if (rawAudioCache.has(key) || inflightFetches.has(key)) return
  void fetchObservabilityCallAudio(callShortId)
}

export function getCachedEvaluatorWaveform(evaluatorResultId: string): CachedWaveform | null {
  const key = playbackKeyForEvaluator(evaluatorResultId)
  const entry = waveformCache.get(key)
  if (!entry) return null
  waveformCache.delete(key)
  waveformCache.set(key, entry)
  return entry
}

export function setCachedEvaluatorWaveform(evaluatorResultId: string, entry: CachedWaveform): void {
  const key = playbackKeyForEvaluator(evaluatorResultId)
  waveformCache.set(key, entry)
  evictOldestIfNeeded()
}

export async function fetchEvaluatorRecordingAudio(
  evaluatorResultId: string,
): Promise<ArrayBuffer | null> {
  const key = playbackKeyForEvaluator(evaluatorResultId)
  const cached = getRawAudioBuffer(key)
  if (cached) return cached

  const inflight = inflightFetches.get(key)
  if (inflight) return inflight

  const promise = apiClient
    .getEvaluatorResultAudioBuffer(evaluatorResultId)
    .then((buffer) => {
      if (buffer?.byteLength) {
        rawAudioCache.set(key, buffer)
        evictRawAudioIfNeeded()
      }
      return buffer
    })
    .catch(() => null)
    .finally(() => {
      inflightFetches.delete(key)
    })

  inflightFetches.set(key, promise)
  return promise
}

export function prefetchEvaluatorRecordingAudio(evaluatorResultId: string): void {
  const key = playbackKeyForEvaluator(evaluatorResultId)
  if (waveformCache.has(key) || rawAudioCache.has(key) || inflightFetches.has(key)) return
  void fetchEvaluatorRecordingAudio(evaluatorResultId)
}

/** Test-only reset for unit tests. */
export function __resetWaveformAudioCacheForTests(): void {
  for (const key of playbackBlobUrls.keys()) {
    revokePlaybackBlobUrl(key)
  }
  waveformCache.clear()
  rawAudioCache.clear()
  inflightFetches.clear()
  playbackBlobRefCounts.clear()
}
