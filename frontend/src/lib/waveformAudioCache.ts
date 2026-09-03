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
  blobUrl: string
}

const MAX_CACHE_ENTRIES = 10
const MAX_RAW_AUDIO_ENTRIES = 12
const waveformCache = new Map<string, CachedWaveform>()
const rawAudioCache = new Map<string, ArrayBuffer>()
const inflightFetches = new Map<string, Promise<ArrayBuffer | null>>()

function cacheKey(callShortId: string, stereo: boolean): string {
  return `${callShortId}:${stereo ? 'stereo' : 'mono'}`
}

function evictOldestMap<T>(map: Map<string, T>, max: number, onEvict?: (value: T) => void): void {
  while (map.size > max) {
    const oldestKey = map.keys().next().value
    if (!oldestKey) break
    const entry = map.get(oldestKey)
    if (entry !== undefined) onEvict?.(entry)
    map.delete(oldestKey)
  }
}

function evictOldestIfNeeded(): void {
  evictOldestMap(waveformCache, MAX_CACHE_ENTRIES)
}

function evictRawAudioIfNeeded(): void {
  evictOldestMap(rawAudioCache, MAX_RAW_AUDIO_ENTRIES)
}

export function preferStereoWaveform(
  callData: Record<string, unknown> | null | undefined,
  platform?: string | null,
): boolean {
  if ((platform || '').toLowerCase() !== 'vapi') return false
  return Boolean(getVapiRecordingTracks(callData).stereo)
}

export function getCachedWaveform(callShortId: string, stereo: boolean): CachedWaveform | null {
  const key = cacheKey(callShortId, stereo)
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
  const key = cacheKey(callShortId, stereo)
  waveformCache.set(key, entry)
  evictOldestIfNeeded()
}

function getRawAudio(key: string): ArrayBuffer | null {
  const entry = rawAudioCache.get(key)
  if (!entry) return null
  rawAudioCache.delete(key)
  rawAudioCache.set(key, entry)
  return entry
}

function setRawAudio(key: string, buffer: ArrayBuffer): void {
  rawAudioCache.set(key, buffer)
  evictRawAudioIfNeeded()
}

export async function fetchCallRecordingAudio(
  callShortId: string,
  stereo: boolean,
): Promise<ArrayBuffer | null> {
  const key = cacheKey(callShortId, stereo)
  const cached = getRawAudio(key)
  if (cached) return cached

  const inflight = inflightFetches.get(key)
  if (inflight) return inflight

  const promise = apiClient
    .getCallRecordingAudioBuffer(callShortId, { stereo })
    .then((buffer) => {
      if (buffer?.byteLength) setRawAudio(key, buffer)
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
  const key = cacheKey(callShortId, stereo)
  if (waveformCache.has(key) || rawAudioCache.has(key) || inflightFetches.has(key)) return
  void fetchCallRecordingAudio(callShortId, stereo)
}

function evaluatorCacheKey(evaluatorResultId: string): string {
  return `eval:${evaluatorResultId}`
}

export function getCachedEvaluatorWaveform(evaluatorResultId: string): CachedWaveform | null {
  const key = evaluatorCacheKey(evaluatorResultId)
  const entry = waveformCache.get(key)
  if (!entry) return null
  waveformCache.delete(key)
  waveformCache.set(key, entry)
  return entry
}

export function setCachedEvaluatorWaveform(evaluatorResultId: string, entry: CachedWaveform): void {
  const key = evaluatorCacheKey(evaluatorResultId)
  waveformCache.set(key, entry)
  evictOldestIfNeeded()
}

export async function fetchEvaluatorRecordingAudio(
  evaluatorResultId: string,
): Promise<ArrayBuffer | null> {
  const key = evaluatorCacheKey(evaluatorResultId)
  const cached = getRawAudio(key)
  if (cached) return cached

  const inflight = inflightFetches.get(key)
  if (inflight) return inflight

  const promise = apiClient
    .getEvaluatorResultAudioBuffer(evaluatorResultId)
    .then((buffer) => {
      if (buffer?.byteLength) setRawAudio(key, buffer)
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
  const key = evaluatorCacheKey(evaluatorResultId)
  if (waveformCache.has(key) || rawAudioCache.has(key) || inflightFetches.has(key)) return
  void fetchEvaluatorRecordingAudio(evaluatorResultId)
}
