export type ChannelEnvelope = {
  duration: number
  sampleRate: number
  numChannels: number
  user: number[]
  agent: number[]
}

export type SpeakerSegmentLike = {
  speaker: string
  start: number
  end: number
}

const DEFAULT_BUCKET_COUNT = 240

function computeRmsBuckets(samples: Float32Array, bucketCount: number): number[] {
  if (samples.length === 0 || bucketCount <= 0) {
    return []
  }

  const samplesPerBucket = Math.max(1, Math.floor(samples.length / bucketCount))
  const buckets: number[] = []

  for (let i = 0; i < bucketCount; i += 1) {
    const start = i * samplesPerBucket
    const end = i === bucketCount - 1 ? samples.length : Math.min(samples.length, start + samplesPerBucket)
    if (start >= end) {
      buckets.push(0)
      continue
    }

    let sumSquares = 0
    for (let j = start; j < end; j += 1) {
      const value = samples[j]
      sumSquares += value * value
    }
    buckets.push(Math.sqrt(sumSquares / (end - start)))
  }

  const peak = Math.max(...buckets, 1e-6)
  return buckets.map((value) => value / peak)
}

export function buildSegmentActivityBuckets(
  segments: SpeakerSegmentLike[],
  duration: number,
  bucketCount: number,
  isUserSpeaker: (speaker: string) => boolean,
): { user: number[]; agent: number[] } {
  const user = new Array(bucketCount).fill(0)
  const agent = new Array(bucketCount).fill(0)
  if (duration <= 0 || bucketCount <= 0) {
    return { user, agent }
  }

  const bucketDuration = duration / bucketCount
  for (const segment of segments) {
    const start = Math.max(0, segment.start)
    const end = Math.max(start, segment.end)
    const startBucket = Math.floor(start / bucketDuration)
    const endBucket = Math.min(bucketCount - 1, Math.ceil(end / bucketDuration))
    const target = isUserSpeaker(segment.speaker) ? user : agent
    for (let bucket = startBucket; bucket <= endBucket; bucket += 1) {
      target[bucket] = 1
    }
  }

  return { user, agent }
}

export async function decodeAudioEnvelope(
  arrayBuffer: ArrayBuffer,
  bucketCount: number = DEFAULT_BUCKET_COUNT,
): Promise<ChannelEnvelope> {
  const audioContext = new AudioContext()
  try {
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer.slice(0))
    const duration = audioBuffer.duration
    const sampleRate = audioBuffer.sampleRate
    const numChannels = audioBuffer.numberOfChannels

    if (numChannels >= 2) {
      return {
        duration,
        sampleRate,
        numChannels,
        user: computeRmsBuckets(audioBuffer.getChannelData(0), bucketCount),
        agent: computeRmsBuckets(audioBuffer.getChannelData(1), bucketCount),
      }
    }

    const mono = computeRmsBuckets(audioBuffer.getChannelData(0), bucketCount)
    return {
      duration,
      sampleRate,
      numChannels,
      user: mono,
      agent: mono.map(() => 0),
    }
  } finally {
    await audioContext.close()
  }
}

export function formatPlaybackTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function isUserSpeakerLabel(speaker: string): boolean {
  const normalized = speaker.trim().toLowerCase()
  return (
    normalized === 'user' ||
    normalized === 'caller' ||
    normalized === 'speaker 1' ||
    normalized === 'customer' ||
    normalized === 'human'
  )
}

export async function fetchAudioArrayBuffer(audioUrl: string): Promise<ArrayBuffer> {
  const response = await fetch(audioUrl, { credentials: 'omit', mode: 'cors' })
  if (!response.ok) {
    throw new Error(`Failed to fetch recording (${response.status})`)
  }
  return response.arrayBuffer()
}

export function buildEnvelopeFromSegments(
  segments: SpeakerSegmentLike[],
  duration: number,
  bucketCount: number = DEFAULT_BUCKET_COUNT,
): ChannelEnvelope {
  const { user, agent } = buildSegmentActivityBuckets(
    segments,
    duration,
    bucketCount,
    isUserSpeakerLabel,
  )
  return {
    duration,
    sampleRate: 24000,
    numChannels: 1,
    user,
    agent,
  }
}
