/** Decode audio from URL and produce normalized peak buckets for waveform rendering. */

export interface AudioPeakData {
  peaks: Float32Array
  durationSec: number
}

let sharedAudioContext: AudioContext | null = null

function getAudioContext(): AudioContext {
  if (!sharedAudioContext) {
    sharedAudioContext = new AudioContext()
  }
  return sharedAudioContext
}

export async function loadAudioPeaks(audioUrl: string, bucketCount = 1600): Promise<AudioPeakData> {
  const response = await fetch(audioUrl)
  if (!response.ok) {
    throw new Error(`Failed to load audio (${response.status})`)
  }
  const buffer = await response.arrayBuffer()
  return decodePeaksFromArrayBuffer(buffer, bucketCount)
}

export async function decodePeaksFromArrayBuffer(
  buffer: ArrayBuffer,
  bucketCount = 1600,
): Promise<AudioPeakData> {
  const ctx = getAudioContext()
  const audioBuffer = await ctx.decodeAudioData(buffer.slice(0))

  const channel = audioBuffer.numberOfChannels > 0 ? audioBuffer.getChannelData(0) : new Float32Array()
  const durationSec = audioBuffer.duration
  const samplesPerBucket = Math.max(1, Math.floor(channel.length / bucketCount))
  const peaks = new Float32Array(bucketCount)

  for (let i = 0; i < bucketCount; i += 1) {
    const start = i * samplesPerBucket
    const end = Math.min(channel.length, start + samplesPerBucket)
    let max = 0
    for (let j = start; j < end; j += 1) {
      const v = Math.abs(channel[j])
      if (v > max) max = v
    }
    peaks[i] = max
  }

  return { peaks, durationSec }
}

/** Fallback when decode fails — flat peaks so segment bars still render. */
export function buildSyntheticPeaks(durationSec: number, bucketCount = 1600): AudioPeakData {
  const peaks = new Float32Array(bucketCount)
  for (let i = 0; i < bucketCount; i += 1) {
    peaks[i] = 0.15 + Math.random() * 0.35
  }
  return { peaks, durationSec: Math.max(durationSec, 1) }
}

export function peaksForTimeRange(
  peaks: Float32Array,
  totalDurationSec: number,
  startSec: number,
  endSec: number,
  targetBuckets = 48,
): Float32Array {
  if (totalDurationSec <= 0 || peaks.length === 0) return new Float32Array(0)
  const startBucket = Math.floor((startSec / totalDurationSec) * peaks.length)
  const endBucket = Math.max(
    startBucket + 1,
    Math.ceil((endSec / totalDurationSec) * peaks.length),
  )
  const slice = peaks.subarray(
    Math.max(0, startBucket),
    Math.min(peaks.length, endBucket),
  )
  if (slice.length <= targetBuckets) return slice

  const out = new Float32Array(targetBuckets)
  const ratio = slice.length / targetBuckets
  for (let i = 0; i < targetBuckets; i += 1) {
    const from = Math.floor(i * ratio)
    const to = Math.min(slice.length, Math.floor((i + 1) * ratio) + 1)
    let max = 0
    for (let j = from; j < to; j += 1) {
      if (slice[j] > max) max = slice[j]
    }
    out[i] = max
  }
  return out
}

export function formatPlaybackTime(seconds: number): string {
  const safe = Math.max(0, seconds)
  const mins = Math.floor(safe / 60)
  const secs = Math.floor(safe % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
