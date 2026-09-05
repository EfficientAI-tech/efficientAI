import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Loader, Pause, Play } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { WAVEFORM_COLORS } from '../../lib/callDetailTheme'
import { extractWavPeaks, isWavBuffer } from '../../lib/waveformPeaksFast'
import {
  fetchCallRecordingAudio,
  fetchEvaluatorRecordingAudio,
  fetchObservabilityCallAudio,
  getCachedEvaluatorWaveform,
  getCachedWaveform,
  getRawAudioBuffer,
  playbackKeyForCall,
  playbackKeyForEvaluator,
  playbackKeyForObservability,
  preferStereoWaveform,
  releasePlaybackBlobUrl,
  resolvePlaybackBlobUrl,
  retainPlaybackBlobUrl,
  setCachedEvaluatorWaveform,
  setCachedWaveform,
  type CachedWaveformTrack,
} from '../../lib/waveformAudioCache'

interface WaveformTrack {
  label: string
  color: string
  mutedColor: string
  peaks: Float32Array
}

interface PaintState {
  tracks: WaveformTrack[]
  progressRatio: number
  duration: number
  showSkeleton: boolean
  showStereoLayout: boolean
}

const TRACK_GAP = 4
const TRACK_HEIGHT = 44
const RULER_HEIGHT = 16
const PEAK_WIDTH = 512

function resolveWaveformCanvasHeight(stereo: boolean): number {
  const trackCount = stereo ? 2 : 1
  return trackCount * TRACK_HEIGHT + (trackCount > 1 ? TRACK_GAP : 0) + RULER_HEIGHT
}

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00'
  const mins = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  return `${String(mins).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function readAudioDuration(audio: HTMLAudioElement | null): number {
  if (!audio) return 0
  const value = audio.duration
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0
}

function resolvePlaybackDuration(audio: HTMLAudioElement | null, fallbackDuration: number): number {
  const fromAudio = readAudioDuration(audio)
  if (fromAudio > 0 && fallbackDuration > 0) return Math.min(fromAudio, fallbackDuration)
  return fromAudio || (fallbackDuration > 0 ? fallbackDuration : 0)
}

function shouldFetchStereo(callData: Record<string, unknown> | null | undefined, platform?: string | null): boolean {
  return preferStereoWaveform(callData, platform)
}

function tracksFromPeaks(peaks: ArrayBuffer[], stereo: boolean): WaveformTrack[] {
  if (stereo && peaks.length >= 2) {
    return [
      {
        label: 'User',
        color: WAVEFORM_COLORS.user,
        mutedColor: 'rgba(251, 146, 60, 0.28)',
        peaks: new Float32Array(peaks[0]),
      },
      {
        label: 'Assistant',
        color: WAVEFORM_COLORS.assistant,
        mutedColor: 'rgba(45, 212, 191, 0.28)',
        peaks: new Float32Array(peaks[1]),
      },
    ]
  }
  return [
    {
      label: 'Call audio',
      color: WAVEFORM_COLORS.mono,
      mutedColor: 'rgba(196, 181, 253, 0.35)',
      peaks: new Float32Array(peaks[0]),
    },
  ]
}

function decodePeaksOnMainThread(
  arrayBuffer: ArrayBuffer,
  stereo: boolean,
): Promise<{ duration: number; tracks: WaveformTrack[] }> {
  return new Promise((resolve, reject) => {
    const ctx = new AudioContext()
    void ctx
      .decodeAudioData(arrayBuffer.slice(0))
      .then((audioBuffer) => {
        if (!audioBuffer) {
          reject(new Error('decode_failed'))
          return
        }
        const width = PEAK_WIDTH
        const useStereo = stereo && audioBuffer.numberOfChannels >= 2
        const downsample = (channel: Float32Array) => {
          const peaks = new Float32Array(width * 2)
          const block = Math.max(1, Math.floor(channel.length / width))
          for (let i = 0; i < width; i++) {
            const start = i * block
            const end = Math.min(channel.length, start + block)
            let min = 0
            let max = 0
            for (let j = start; j < end; j++) {
              const v = channel[j]
              if (v < min) min = v
              if (v > max) max = v
            }
            peaks[i * 2] = min
            peaks[i * 2 + 1] = max
          }
          return peaks
        }

        const peakBuffers: ArrayBuffer[] = []
        if (useStereo) {
          peakBuffers.push(downsample(audioBuffer.getChannelData(0)).buffer)
          peakBuffers.push(downsample(audioBuffer.getChannelData(1)).buffer)
        } else {
          peakBuffers.push(downsample(audioBuffer.getChannelData(0)).buffer)
        }

        resolve({
          duration: audioBuffer.duration,
          tracks: tracksFromPeaks(peakBuffers, useStereo),
        })
      })
      .catch(() => reject(new Error('decode_failed')))
      .finally(() => {
        void ctx.close()
      })
  })
}

async function buildWaveformTracks(
  arrayBuffer: ArrayBuffer,
  stereo: boolean,
): Promise<{ duration: number; tracks: WaveformTrack[] }> {
  if (isWavBuffer(arrayBuffer)) {
    const wav = extractWavPeaks(arrayBuffer, stereo, PEAK_WIDTH)
    if (wav) {
      return {
        duration: wav.duration,
        tracks: tracksFromPeaks(wav.peaks, wav.stereo),
      }
    }
  }
  return decodePeaksOnMainThread(arrayBuffer, stereo)
}

function drawMirroredTrack(
  ctx: CanvasRenderingContext2D,
  peaks: Float32Array,
  width: number,
  height: number,
  yOffset: number,
  activeColor: string,
  mutedColor: string,
  progressRatio: number,
) {
  const barCount = peaks.length / 2
  const midY = yOffset + height / 2
  const amp = height * 0.46
  const barW = Math.max(1.5, width / barCount - 0.5)
  const playedBars = Math.floor(barCount * progressRatio)

  for (let i = 0; i < barCount; i++) {
    const min = peaks[i * 2]
    const max = peaks[i * 2 + 1]
    const x = (i / barCount) * width
    const magnitude = Math.max(Math.abs(min), Math.abs(max))
    const barH = Math.max(2, magnitude * amp * 2)
    const top = midY - barH / 2
    ctx.fillStyle = i <= playedBars ? activeColor : mutedColor
    ctx.fillRect(x, top, barW, barH)
  }

  ctx.strokeStyle = 'rgba(20, 184, 166, 0.35)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(0, midY)
  ctx.lineTo(width, midY)
  ctx.stroke()
}

function drawSkeletonTrack(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  yOffset: number,
  color: string,
) {
  const midY = yOffset + height / 2
  const barCount = 80
  const barW = Math.max(1.5, width / barCount - 0.5)
  for (let i = 0; i < barCount; i++) {
    const x = (i / barCount) * width
    const barH = 6 + ((i * 17) % 11)
    ctx.fillStyle = color
    ctx.fillRect(x, midY - barH / 2, barW, barH)
  }
}

function drawTimeRuler(
  ctx: CanvasRenderingContext2D,
  width: number,
  y: number,
  duration: number,
) {
  if (duration <= 0) return
  const step = duration <= 30 ? 5 : duration <= 120 ? 10 : 30
  ctx.fillStyle = 'rgba(148, 163, 184, 0.9)'
  ctx.font = '10px ui-monospace, monospace'
  for (let t = 0; t <= duration; t += step) {
    const x = (t / duration) * width
    ctx.fillRect(x, y, 1, 6)
    if (t > 0) ctx.fillText(String(t), x + 3, y + 16)
  }
}

function paintCanvas(canvas: HTMLCanvasElement, container: HTMLDivElement, state: PaintState): void {
  const width = container.clientWidth
  if (width <= 0) return

  const trackCount = state.showStereoLayout ? 2 : Math.max(state.tracks.length, 1)
  const waveformHeight = trackCount * TRACK_HEIGHT + (trackCount > 1 ? TRACK_GAP : 0)
  const rulerHeight = 22
  const height = waveformHeight + rulerHeight
  const dpr = window.devicePixelRatio || 1

  canvas.width = width * dpr
  canvas.height = height * dpr
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`

  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = WAVEFORM_COLORS.canvasBg
  ctx.fillRect(0, 0, width, height)

  if (state.showSkeleton || state.tracks.length === 0) {
    drawSkeletonTrack(ctx, width, TRACK_HEIGHT, 0, WAVEFORM_COLORS.skeleton)
    if (trackCount > 1) {
      drawSkeletonTrack(ctx, width, TRACK_HEIGHT, TRACK_HEIGHT + TRACK_GAP, 'rgba(148, 163, 184, 0.18)')
    }
  } else {
    state.tracks.forEach((track, index) => {
      const y = index * (TRACK_HEIGHT + TRACK_GAP)
      drawMirroredTrack(
        ctx,
        track.peaks,
        width,
        TRACK_HEIGHT,
        y,
        track.color,
        track.mutedColor,
        state.progressRatio,
      )
    })
  }

  const playX = state.progressRatio * width
  ctx.strokeStyle = WAVEFORM_COLORS.playhead
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(playX, 0)
  ctx.lineTo(playX, waveformHeight)
  ctx.stroke()
  drawTimeRuler(ctx, width, waveformHeight + 4, state.duration)
}

export default function CallWaveformPlayer({
  callShortId,
  observabilityCallShortId,
  callRecordingId,
  evaluatorResultId,
  callData,
  platform,
  audioRevision,
}: {
  callShortId?: string
  observabilityCallShortId?: string
  callRecordingId?: string | null
  evaluatorResultId?: string
  callData?: Record<string, unknown> | null
  platform?: string | null
  audioRevision?: string | null
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const blobRef = useRef<string | null>(null)
  const playbackKeyRef = useRef<string | null>(null)
  const usingStreamPlaybackRef = useRef(false)
  const draggingRef = useRef(false)
  const loadedStereoRef = useRef(false)
  const decodeTaskRef = useRef(0)
  const pendingPlaybackRestoreRef = useRef<{ time: number; play: boolean } | null>(null)
  const paintStateRef = useRef<PaintState>({
    tracks: [],
    progressRatio: 0,
    duration: 0,
    showSkeleton: false,
    showStereoLayout: false,
  })
  const callDataRef = useRef(callData)
  const platformRef = useRef(platform)
  callDataRef.current = callData
  platformRef.current = platform

  const [tracks, setTracks] = useState<WaveformTrack[]>([])
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [fetching, setFetching] = useState(false)
  const [decoding, setDecoding] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [playbackReady, setPlaybackReady] = useState(false)
  const waveformDecodedKeyRef = useRef<string | null>(null)
  const pendingWaveformFetchRef = useRef<{
    playbackKey: string
    fetchBuffer: () => Promise<ArrayBuffer | null>
    decodeOptions?: {
      cacheCallShortId?: string
      cacheEvaluatorId?: string
      stereo?: boolean
    }
  } | null>(null)

  const wantStereo = useMemo(() => shouldFetchStereo(callData, platform), [callData, platform])
  const showStereoLayout = wantStereo || tracks.length > 1
  const waveformCanvasHeight = resolveWaveformCanvasHeight(showStereoLayout)
  const progressRatio = duration > 0 ? Math.max(0, Math.min(1, currentTime / duration)) : 0
  const showSkeleton = decoding && tracks.length === 0

  paintStateRef.current = {
    tracks,
    progressRatio,
    duration,
    showSkeleton,
    showStereoLayout,
  }

  const repaint = useCallback(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    paintCanvas(canvas, container, paintStateRef.current)
  }, [])

  const bindPlaybackUrl = useCallback((playbackKey: string, playbackUrl: string) => {
    const isBlob = playbackUrl.startsWith('blob:')
    if (playbackKeyRef.current && !usingStreamPlaybackRef.current) {
      releasePlaybackBlobUrl(playbackKeyRef.current)
    }
    usingStreamPlaybackRef.current = !isBlob
    if (isBlob) {
      retainPlaybackBlobUrl(playbackKey)
      playbackKeyRef.current = playbackKey
    } else {
      playbackKeyRef.current = null
    }
    blobRef.current = playbackUrl
    setPlaybackReady(false)
    setAudioUrl(playbackUrl)
  }, [])

  const setStreamPlaybackUrl = useCallback((url: string) => {
    if (playbackKeyRef.current && !usingStreamPlaybackRef.current) {
      releasePlaybackBlobUrl(playbackKeyRef.current)
    }
    usingStreamPlaybackRef.current = true
    playbackKeyRef.current = null
    blobRef.current = url
    setPlaybackReady(false)
    setAudioUrl(url)
    setFetching(false)
  }, [])

  const upgradeStreamToBlobPlayback = useCallback(
    (playbackKey: string, arrayBuffer: ArrayBuffer) => {
      if (!usingStreamPlaybackRef.current || !arrayBuffer?.byteLength) return false
      const blobUrl = resolvePlaybackBlobUrl(playbackKey, arrayBuffer)
      if (!blobUrl) return false
      const audio = audioRef.current
      const restoreTime = audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0
      const restorePlay = Boolean(audio && !audio.paused && !audio.ended)
      pendingPlaybackRestoreRef.current = { time: restoreTime, play: restorePlay }
      bindPlaybackUrl(playbackKey, blobUrl)
      return true
    },
    [bindPlaybackUrl],
  )

  const decodeAndSetTracks = useCallback(
    async (
      arrayBuffer: ArrayBuffer,
      stereo: boolean,
      options?: {
        cacheCallShortId?: string
        cacheEvaluatorId?: string
        usedStereo?: boolean
        cancelled?: () => boolean
        upgrade?: boolean
      },
    ) => {
      const taskId = ++decodeTaskRef.current
      if (!options?.upgrade || tracks.length === 0) {
        setDecoding(true)
      }
      try {
        const { duration: decodedDuration, tracks: decodedTracks } = await buildWaveformTracks(
          arrayBuffer,
          stereo,
        )
        if (taskId !== decodeTaskRef.current || options?.cancelled?.()) return

        setTracks(decodedTracks)
        setDuration((prev) => {
          const fromAudio = readAudioDuration(audioRef.current)
          if (fromAudio > 0) return fromAudio
          if (Number.isFinite(decodedDuration) && decodedDuration > 0) return decodedDuration
          return prev
        })
        setDecoding(false)
        setLoadError(null)
        if (stereo && decodedTracks.length > 1) loadedStereoRef.current = true

        if (options?.cacheEvaluatorId) {
          setCachedEvaluatorWaveform(options.cacheEvaluatorId, {
            tracks: decodedTracks as CachedWaveformTrack[],
            duration: decodedDuration,
          })
        } else if (options?.cacheCallShortId) {
          setCachedWaveform(options.cacheCallShortId, options.usedStereo ?? stereo, {
            tracks: decodedTracks as CachedWaveformTrack[],
            duration: decodedDuration,
          })
        }
      } catch {
        if (taskId === decodeTaskRef.current) {
          setDecoding(false)
          setLoadError('Could not render waveform for this recording.')
        }
      }
    },
    [],
  )

  const runPendingWaveformFetch = useCallback(
    (cancelled?: () => boolean) => {
      const pending = pendingWaveformFetchRef.current
      if (!pending) return
      pendingWaveformFetchRef.current = null

      void (async () => {
        try {
          const arrayBuffer = await pending.fetchBuffer()
          if (!arrayBuffer?.byteLength || cancelled?.()) return

          upgradeStreamToBlobPlayback(pending.playbackKey, arrayBuffer)
          if (waveformDecodedKeyRef.current === pending.playbackKey) return
          waveformDecodedKeyRef.current = pending.playbackKey
          void decodeAndSetTracks(arrayBuffer, pending.decodeOptions?.stereo ?? false, {
            cacheCallShortId: pending.decodeOptions?.cacheCallShortId,
            cacheEvaluatorId: pending.decodeOptions?.cacheEvaluatorId,
            usedStereo: pending.decodeOptions?.stereo ?? false,
            cancelled,
          })
        } catch {
          if (!cancelled?.()) {
            setLoadError('Could not load recording audio.')
          }
        }
      })()
    },
    [decodeAndSetTracks, upgradeStreamToBlobPlayback],
  )

  useEffect(() => {
    let cancelled = false
    const isCancelled = () => cancelled
    pendingWaveformFetchRef.current = null
    loadedStereoRef.current = false
    waveformDecodedKeyRef.current = null
    decodeTaskRef.current += 1
    setPlaying(false)
    setCurrentTime(0)
    setPlaybackReady(false)
    setTracks([])
    setDuration(0)
    setLoadError(null)
    audioRef.current?.pause()

    function applyCached(
      cached: ReturnType<typeof getCachedWaveform>,
      playbackKey: string,
    ) {
      if (!cached || cancelled) return false
      const buffer = getRawAudioBuffer(playbackKey)
      const playbackUrl = resolvePlaybackBlobUrl(playbackKey, buffer)
      if (!playbackUrl) return false
      bindPlaybackUrl(playbackKey, playbackUrl)
      setTracks(Array.isArray(cached.tracks) ? cached.tracks : [])
      setDuration(
        typeof cached.duration === 'number' && Number.isFinite(cached.duration) ? cached.duration : 0,
      )
      setFetching(false)
      setDecoding(false)
      setLoadError(null)
      loadedStereoRef.current = cached.tracks.length > 1
      return true
    }

    function applyPrefetchedBuffer(
      playbackKey: string,
      decodeOptions?: {
        cacheCallShortId?: string
        cacheEvaluatorId?: string
        stereo?: boolean
      },
    ) {
      const buffer = getRawAudioBuffer(playbackKey)
      const playbackUrl = resolvePlaybackBlobUrl(playbackKey, buffer)
      if (!buffer?.byteLength || !playbackUrl || cancelled) return false
      bindPlaybackUrl(playbackKey, playbackUrl)
      setFetching(false)
      setDecoding(true)
      setLoadError(null)
      void decodeWaveformOnce(
        playbackKey,
        buffer,
        decodeOptions?.stereo ?? false,
        decodeOptions?.cacheCallShortId,
        decodeOptions?.cacheEvaluatorId,
      )
      return true
    }

    async function decodeWaveformOnce(
      playbackKey: string,
      arrayBuffer: ArrayBuffer,
      stereo: boolean,
      cacheCallShortId?: string,
      cacheEvaluatorId?: string,
      upgrade = false,
    ) {
      if (!arrayBuffer?.byteLength || cancelled) return
      if (waveformDecodedKeyRef.current === playbackKey && !upgrade) return
      if (!upgrade) waveformDecodedKeyRef.current = playbackKey
      loadedStereoRef.current = stereo && !upgrade ? loadedStereoRef.current : stereo
      void decodeAndSetTracks(arrayBuffer, stereo, {
        cacheCallShortId,
        cacheEvaluatorId,
        usedStereo: stereo,
        cancelled: isCancelled,
        upgrade,
      })
    }

    async function startStreamPlaybackWithBackgroundWaveform(
      streamUrl: string,
      playbackKey: string,
      fetchBuffer: () => Promise<ArrayBuffer | null>,
      decodeOptions?: {
        cacheCallShortId?: string
        cacheEvaluatorId?: string
        stereo?: boolean
      },
    ) {
      const cachedBuffer = getRawAudioBuffer(playbackKey)
      if (cachedBuffer?.byteLength) {
        const blobUrl = resolvePlaybackBlobUrl(playbackKey, cachedBuffer)
        if (blobUrl) {
          bindPlaybackUrl(playbackKey, blobUrl)
          setFetching(false)
          void decodeWaveformOnce(
            playbackKey,
            cachedBuffer,
            decodeOptions?.stereo ?? false,
            decodeOptions?.cacheCallShortId,
            decodeOptions?.cacheEvaluatorId,
          )
          return
        }
      }

      setStreamPlaybackUrl(streamUrl)
      setDecoding(true)
      pendingWaveformFetchRef.current = {
        playbackKey,
        fetchBuffer,
        decodeOptions,
      }

      window.setTimeout(() => {
        if (!cancelled && pendingWaveformFetchRef.current?.playbackKey === playbackKey) {
          runPendingWaveformFetch(isCancelled)
        }
      }, 2500)
    }

    async function load() {
      if (!callRecordingId && !callShortId && !evaluatorResultId && !observabilityCallShortId) return

      const stereo = shouldFetchStereo(callDataRef.current, platformRef.current)

      if (callShortId) {
        const monoKey = playbackKeyForCall(callShortId, false)
        const stereoKey = playbackKeyForCall(callShortId, stereo)
        if (applyCached(getCachedWaveform(callShortId, stereo), stereoKey)) return
        if (!stereo && applyCached(getCachedWaveform(callShortId, false), monoKey)) return
        if (applyPrefetchedBuffer(monoKey, { cacheCallShortId: callShortId, stereo: false })) return
      }
      if (evaluatorResultId) {
        const evalKey = playbackKeyForEvaluator(evaluatorResultId)
        if (applyCached(getCachedEvaluatorWaveform(evaluatorResultId), evalKey)) return
        if (applyPrefetchedBuffer(evalKey, { cacheEvaluatorId: evaluatorResultId })) return
      }

      setFetching(true)
      setAudioUrl(null)
      setDecoding(false)
      setLoadError(null)

      if (callShortId) {
        await startStreamPlaybackWithBackgroundWaveform(
          apiClient.getCallRecordingAudioStreamUrl(callShortId, { stereo: false }),
          playbackKeyForCall(callShortId, false),
          () => fetchCallRecordingAudio(callShortId, false),
          { cacheCallShortId: callShortId, stereo: false },
        )
        return
      }

      if (observabilityCallShortId) {
        await startStreamPlaybackWithBackgroundWaveform(
          apiClient.getObservabilityCallAudioStreamUrl(observabilityCallShortId),
          playbackKeyForObservability(observabilityCallShortId),
          () => fetchObservabilityCallAudio(observabilityCallShortId),
        )
        return
      }

      if (evaluatorResultId) {
        await startStreamPlaybackWithBackgroundWaveform(
          apiClient.getEvaluatorResultAudioStreamUrl(evaluatorResultId),
          playbackKeyForEvaluator(evaluatorResultId),
          () => fetchEvaluatorRecordingAudio(evaluatorResultId),
          { cacheEvaluatorId: evaluatorResultId },
        )
        return
      }

      if (!cancelled) {
        setFetching(false)
        setLoadError('Recording unavailable.')
      }
    }

    void load()
    return () => {
      cancelled = true
      pendingWaveformFetchRef.current = null
      decodeTaskRef.current += 1
      audioRef.current?.pause()
      if (playbackKeyRef.current && !usingStreamPlaybackRef.current) {
        releasePlaybackBlobUrl(playbackKeyRef.current)
        playbackKeyRef.current = null
      }
      usingStreamPlaybackRef.current = false
    }
  }, [
    callRecordingId,
    callShortId,
    observabilityCallShortId,
    evaluatorResultId,
    audioRevision,
    decodeAndSetTracks,
    setStreamPlaybackUrl,
    bindPlaybackUrl,
    upgradeStreamToBlobPlayback,
    runPendingWaveformFetch,
  ])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !audioUrl) return

    const syncDuration = () => {
      const nextDuration = readAudioDuration(audio)
      if (nextDuration > 0) {
        setDuration(nextDuration)
      }
    }

    const markPlaybackReady = () => {
      syncDuration()
      if (audio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        setPlaybackReady(true)
      }
    }

    const restorePending = () => {
      markPlaybackReady()
      const pending = pendingPlaybackRestoreRef.current
      if (!pending) return
      const nextTime = Math.min(pending.time, audio.duration || pending.time)
      audio.currentTime = nextTime
      setCurrentTime(nextTime)
      paintStateRef.current.progressRatio = audio.duration > 0 ? nextTime / audio.duration : 0
      repaint()
      if (pending.play) {
        void audio.play().catch(() => undefined)
      }
      pendingPlaybackRestoreRef.current = null
    }

    const onLoadedMetadata = () => restorePending()
    const onCanPlay = () => markPlaybackReady()
    const onDurationChange = () => syncDuration()

    audio.addEventListener('loadedmetadata', onLoadedMetadata)
    audio.addEventListener('canplay', onCanPlay)
    audio.addEventListener('durationchange', onDurationChange)
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) onLoadedMetadata()
    if (audio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) onCanPlay()

    return () => {
      audio.removeEventListener('loadedmetadata', onLoadedMetadata)
      audio.removeEventListener('canplay', onCanPlay)
      audio.removeEventListener('durationchange', onDurationChange)
    }
  }, [audioUrl, repaint])

  useEffect(() => {
    if (!callShortId || !wantStereo || loadedStereoRef.current || tracks.length !== 1 || decoding) return

    const stereoKey = playbackKeyForCall(callShortId, true)
    let cancelled = false
    void (async () => {
      const arrayBuffer = await fetchCallRecordingAudio(callShortId, true)
      if (!arrayBuffer?.byteLength || cancelled) return
      if (waveformDecodedKeyRef.current === stereoKey) return
      waveformDecodedKeyRef.current = stereoKey
      await decodeAndSetTracks(arrayBuffer, true, {
        cacheCallShortId: callShortId,
        usedStereo: true,
        cancelled: () => cancelled,
        upgrade: true,
      })
    })()

    return () => {
      cancelled = true
    }
  }, [callShortId, wantStereo, tracks.length, decoding, decodeAndSetTracks])

  useEffect(() => {
    repaint()
  }, [tracks, duration, showSkeleton, showStereoLayout, waveformCanvasHeight, repaint])

  useEffect(() => {
    const onResize = () => repaint()
    window.addEventListener('resize', onResize)
    const container = containerRef.current
    let observer: ResizeObserver | undefined
    if (container && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => repaint())
      observer.observe(container)
    }
    return () => {
      window.removeEventListener('resize', onResize)
      observer?.disconnect()
    }
  }, [repaint])

  useEffect(() => {
    if (!playing) return
    let frame = 0
    let lastUiUpdate = 0
    const tick = (now: number) => {
      const audio = audioRef.current
      if (audio) {
        const d = resolvePlaybackDuration(audio, duration)
        if (d > 0) {
          const ratio = Math.max(0, Math.min(1, audio.currentTime / d))
          paintStateRef.current.progressRatio = ratio
          repaint()
          if (now - lastUiUpdate > 250) {
            setCurrentTime(audio.currentTime)
            lastUiUpdate = now
          }
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, duration, repaint])

  const seekFromClientX = useCallback(
    (clientX: number) => {
      const container = containerRef.current
      const audio = audioRef.current
      if (!container || !audio) return
      const audioDuration = resolvePlaybackDuration(audio, duration)
      if (!audioDuration) return
      const rect = container.getBoundingClientRect()
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      const nextTime = Math.min(ratio * audioDuration, Math.max(0, audioDuration - 0.05))
      if (audio.ended) {
        audio.pause()
      }
      audio.currentTime = nextTime
      setCurrentTime(nextTime)
      paintStateRef.current.progressRatio = audioDuration > 0 ? nextTime / audioDuration : 0
      repaint()
    },
    [duration, repaint],
  )

  const togglePlay = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (playing) {
      audio.pause()
      return
    }
    const audioDuration = resolvePlaybackDuration(audio, duration)
    if (audioDuration > 0 && (audio.ended || audio.currentTime >= audioDuration - 0.05)) {
      audio.currentTime = 0
      setCurrentTime(0)
      paintStateRef.current.progressRatio = 0
      repaint()
    }
    audio.playbackRate = playbackRate
    try {
      await audio.play()
    } catch {
      // ignore autoplay / interruption errors
    }
  }

  useEffect(() => {
    const audio = audioRef.current
    if (audio) audio.playbackRate = playbackRate
  }, [playbackRate])

  const handleDownload = async () => {
    if (!callShortId) return
    try {
      const blobUrl = await apiClient.getCallRecordingAudioUrl(callShortId, {
        stereo: loadedStereoRef.current,
      })
      const anchor = document.createElement('a')
      anchor.href = blobUrl
      anchor.download = `call-${callShortId}.wav`
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
    } catch {
      setLoadError('Download failed. Try Refresh on the call first.')
    }
  }

  if (!callRecordingId && !callShortId && !evaluatorResultId && !observabilityCallShortId) return null

  const canPlay = playbackReady && Boolean(audioUrl)
  const canSeek = playbackReady && duration > 0
  const showStatusOverlay = (fetching && !audioUrl) || (loadError && !audioUrl)

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-3 py-1.5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Recording</p>
        <span className="font-mono text-xs tabular-nums text-gray-600">
          {formatClock(currentTime)} / {duration > 0 ? formatClock(duration) : '--:--'}
        </span>
      </div>

      <div className="px-3 pb-1 pt-2">
        {showStereoLayout ? (
          <div className="mb-1.5 flex h-4 gap-4 px-1 text-[10px] font-semibold uppercase tracking-wider">
            <span className="text-orange-500">User</span>
            <span className="text-teal-500">Assistant</span>
          </div>
        ) : null}

        <div className="relative" style={{ height: waveformCanvasHeight }}>
          {showStatusOverlay ? (
            <div className="absolute inset-0 z-20 flex items-center justify-center rounded-lg bg-white px-4 text-center text-sm text-gray-500">
              {fetching ? (
                <>
                  <Loader className="mr-2 h-4 w-4 animate-spin" />
                  Loading audio…
                </>
              ) : (
                <span className="text-amber-700">{loadError}</span>
              )}
            </div>
          ) : null}

          <div
            ref={containerRef}
            className={`relative h-full select-none rounded-lg ${canSeek ? 'cursor-pointer' : 'cursor-default'} ${
              showStatusOverlay ? 'pointer-events-none opacity-0' : ''
            }`}
            onPointerDown={(e) => {
              if (!canSeek) return
              draggingRef.current = true
              e.currentTarget.setPointerCapture(e.pointerId)
              seekFromClientX(e.clientX)
            }}
            onPointerMove={(e) => {
              if (draggingRef.current) seekFromClientX(e.clientX)
            }}
            onPointerUp={(e) => {
              draggingRef.current = false
              if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId)
              }
            }}
            onPointerCancel={(e) => {
              draggingRef.current = false
              if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId)
              }
            }}
          >
            {decoding && tracks.length === 0 && !loadError && audioUrl ? (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-white/60">
                <Loader className="h-4 w-4 animate-spin text-gray-400" />
              </div>
            ) : null}
            <canvas ref={canvasRef} className="block h-full w-full rounded-lg" />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 px-3 py-2">
        <button
          type="button"
          onClick={() => void togglePlay()}
          disabled={!canPlay}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-primary-400 text-primary-900 shadow-md shadow-primary-200/80 hover:bg-primary-300 disabled:opacity-40"
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="ml-0.5 h-4 w-4" />}
        </button>

        <select
          value={playbackRate}
          onChange={(e) => setPlaybackRate(Number(e.target.value))}
          className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-700"
        >
          {[0.75, 1, 1.25, 1.5, 2].map((rate) => (
            <option key={rate} value={rate}>
              {rate}x
            </option>
          ))}
        </select>

        {callShortId ? (
          <button
            type="button"
            onClick={() => void handleDownload()}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            <Download className="h-3.5 w-3.5" />
            Audio
          </button>
        ) : null}
      </div>

      <audio
        ref={audioRef}
        src={audioUrl ?? undefined}
        preload="auto"
        className="hidden"
        onLoadedMetadata={(e) => {
          const el = e.currentTarget
          const nextDuration = el?.duration
          if (typeof nextDuration === 'number' && Number.isFinite(nextDuration) && nextDuration > 0) {
            setDuration(nextDuration)
          }
        }}
        onCanPlay={() => {
          setPlaybackReady(true)
          runPendingWaveformFetch()
        }}
        onTimeUpdate={(e) => {
          if (draggingRef.current) return
          const el = e.currentTarget
          if (!Number.isFinite(el.currentTime)) return
          setCurrentTime(el.currentTime)
          const d = resolvePlaybackDuration(el, duration)
          if (d > 0) {
            paintStateRef.current.progressRatio = Math.max(0, Math.min(1, el.currentTime / d))
            repaint()
          }
        }}
        onSeeked={(e) => {
          const el = e.currentTarget
          if (!Number.isFinite(el.currentTime)) return
          setCurrentTime(el.currentTime)
          const d = resolvePlaybackDuration(el, duration)
          if (d > 0) {
            paintStateRef.current.progressRatio = Math.max(0, Math.min(1, el.currentTime / d))
            repaint()
          }
        }}
        onEnded={() => {
          setPlaying(false)
          const el = audioRef.current
          const d = resolvePlaybackDuration(el, duration)
          if (el && d > 0) {
            setCurrentTime(d)
            paintStateRef.current.progressRatio = 1
            repaint()
          }
        }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />
    </div>
  )
}
