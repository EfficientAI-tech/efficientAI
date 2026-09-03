import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Loader, Pause, Play } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { WAVEFORM_COLORS } from '../../lib/callDetailTheme'
import { extractWavPeaks, isWavBuffer } from '../../lib/waveformPeaksFast'
import {
  fetchCallRecordingAudio,
  fetchEvaluatorRecordingAudio,
  getCachedEvaluatorWaveform,
  getCachedWaveform,
  preferStereoWaveform,
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

const TRACK_GAP = 6
const TRACK_HEIGHT = 52
const PEAK_WIDTH = 512

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00'
  const mins = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  return `${String(mins).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function shouldFetchStereo(callData: Record<string, unknown> | null | undefined, platform?: string | null): boolean {
  const platformName = (platform || '').toLowerCase()
  return preferStereoWaveform(callData, platform) || platformName === 'vapi'
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

function createBlobUrl(arrayBuffer: ArrayBuffer): string {
  return URL.createObjectURL(new Blob([arrayBuffer], { type: guessAudioMimeType(arrayBuffer) }))
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
  callRecordingId,
  evaluatorResultId,
  callData,
  platform,
}: {
  callShortId?: string
  callRecordingId?: string | null
  evaluatorResultId?: string
  callData?: Record<string, unknown> | null
  platform?: string | null
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const blobRef = useRef<string | null>(null)
  const ownsBlobRef = useRef(false)
  const draggingRef = useRef(false)
  const loadedStereoRef = useRef(false)
  const decodeTaskRef = useRef(0)
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

  const wantStereo = useMemo(() => shouldFetchStereo(callData, platform), [callData, platform])
  const showStereoLayout = tracks.length > 1 || (wantStereo && decoding)
  const progressRatio = duration > 0 ? currentTime / duration : 0
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

  const setBlobFromBuffer = useCallback((arrayBuffer: ArrayBuffer) => {
    if (blobRef.current && ownsBlobRef.current) URL.revokeObjectURL(blobRef.current)
    const url = createBlobUrl(arrayBuffer)
    blobRef.current = url
    ownsBlobRef.current = true
    setAudioUrl(url)
    return url
  }, [])

  const setStreamAudioUrl = useCallback((url: string) => {
    if (blobRef.current && ownsBlobRef.current) URL.revokeObjectURL(blobRef.current)
    blobRef.current = url
    ownsBlobRef.current = false
    setAudioUrl(url)
    return url
  }, [])

  const decodeAndSetTracks = useCallback(
    async (
      arrayBuffer: ArrayBuffer,
      stereo: boolean,
      options?: {
        cacheCallShortId?: string
        cacheEvaluatorId?: string
        usedStereo?: boolean
        blobUrl?: string
        cancelled?: () => boolean
      },
    ) => {
      const taskId = ++decodeTaskRef.current
      setDecoding(true)
      try {
        const { duration: decodedDuration, tracks: decodedTracks } = await buildWaveformTracks(
          arrayBuffer,
          stereo,
        )
        if (taskId !== decodeTaskRef.current || options?.cancelled?.()) return

        setTracks(decodedTracks)
        setDuration((prev) => (prev > 0 ? prev : decodedDuration))
        setDecoding(false)
        setLoadError(null)
        if (stereo && decodedTracks.length > 1) loadedStereoRef.current = true

        const blobUrl = options?.blobUrl ?? blobRef.current
        if (!blobUrl || options?.cancelled?.()) return

        if (options?.cacheEvaluatorId) {
          setCachedEvaluatorWaveform(options.cacheEvaluatorId, {
            tracks: decodedTracks as CachedWaveformTrack[],
            duration: decodedDuration,
            blobUrl,
          })
          ownsBlobRef.current = false
        } else if (options?.cacheCallShortId) {
          setCachedWaveform(options.cacheCallShortId, options.usedStereo ?? stereo, {
            tracks: decodedTracks as CachedWaveformTrack[],
            duration: decodedDuration,
            blobUrl,
          })
          ownsBlobRef.current = false
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

  useEffect(() => {
    let cancelled = false
    const isCancelled = () => cancelled
    loadedStereoRef.current = false
    decodeTaskRef.current += 1
    setPlaying(false)
    setCurrentTime(0)

    function applyCached(cached: ReturnType<typeof getCachedWaveform>) {
      if (!cached || cancelled) return false
      if (blobRef.current && ownsBlobRef.current) URL.revokeObjectURL(blobRef.current)
      blobRef.current = cached.blobUrl
      ownsBlobRef.current = false
      setAudioUrl(cached.blobUrl)
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

    async function loadWaveformFromBuffer(
      arrayBuffer: ArrayBuffer,
      stereo: boolean,
      cacheCallShortId?: string,
      cacheEvaluatorId?: string,
      usedStereo?: boolean,
      blobUrl?: string,
    ) {
      if (!arrayBuffer?.byteLength || cancelled) return
      const playbackUrl = blobUrl ?? blobRef.current
      if (!playbackUrl) return
      loadedStereoRef.current = usedStereo ?? stereo
      void decodeAndSetTracks(arrayBuffer, stereo, {
        cacheCallShortId,
        cacheEvaluatorId,
        usedStereo: usedStereo ?? stereo,
        blobUrl: playbackUrl,
        cancelled: isCancelled,
      })
    }

    async function load() {
      if (!callRecordingId && !callShortId && !evaluatorResultId) return

      const stereo = shouldFetchStereo(callDataRef.current, platformRef.current)

      if (callShortId && applyCached(getCachedWaveform(callShortId, stereo))) return
      if (callShortId && !stereo && applyCached(getCachedWaveform(callShortId, false))) return
      if (evaluatorResultId && applyCached(getCachedEvaluatorWaveform(evaluatorResultId))) return

      setDecoding(false)
      setLoadError(null)
      setTracks([])
      setDuration(0)
      setCurrentTime(0)

      if (callShortId) {
        setStreamAudioUrl(apiClient.getCallRecordingAudioStreamUrl(callShortId, { stereo: false }))
        setFetching(false)

        void (async () => {
          try {
            const arrayBuffer = await fetchCallRecordingAudio(callShortId, false)
            if (!arrayBuffer?.byteLength || cancelled) {
              if (!cancelled) {
                setLoadError('Recording unavailable. Refresh the call to renew provider audio URLs.')
              }
              return
            }
            await loadWaveformFromBuffer(arrayBuffer, false, callShortId, undefined, false)
          } catch {
            if (!cancelled) setLoadError('Could not load recording waveform.')
          }
        })()
        return
      }

      setFetching(true)
      setAudioUrl(null)

      try {
        let arrayBuffer: ArrayBuffer | null = null
        let usedStereo = false
        let cacheEvaluatorId: string | undefined

        if (evaluatorResultId) {
          arrayBuffer = await fetchEvaluatorRecordingAudio(evaluatorResultId)
          cacheEvaluatorId = evaluatorResultId
        }

        if (!arrayBuffer?.byteLength || cancelled) {
          if (!cancelled) {
            setLoadError('Recording unavailable for this evaluation run.')
          }
          return
        }

        const blobUrl = setBlobFromBuffer(arrayBuffer)
        setFetching(false)
        loadedStereoRef.current = usedStereo

        void decodeAndSetTracks(arrayBuffer, usedStereo, {
          cacheEvaluatorId,
          usedStereo,
          blobUrl,
          cancelled: isCancelled,
        })
      } catch {
        if (!cancelled) setLoadError('Could not load recording audio.')
      } finally {
        if (!cancelled) setFetching(false)
      }
    }

    void load()
    return () => {
      cancelled = true
      decodeTaskRef.current += 1
      if (blobRef.current && ownsBlobRef.current) URL.revokeObjectURL(blobRef.current)
    }
  }, [callRecordingId, callShortId, evaluatorResultId, decodeAndSetTracks, setBlobFromBuffer, setStreamAudioUrl])

  useEffect(() => {
    if (!callShortId || !wantStereo || loadedStereoRef.current || tracks.length > 1) return

    let cancelled = false
    void (async () => {
      const arrayBuffer = await fetchCallRecordingAudio(callShortId, true)
      if (!arrayBuffer?.byteLength || cancelled) return
      const playbackUrl = blobRef.current
      if (!playbackUrl) return
      await decodeAndSetTracks(arrayBuffer, true, {
        cacheCallShortId: callShortId,
        usedStereo: true,
        blobUrl: playbackUrl,
        cancelled: () => cancelled,
      })
    })()

    return () => {
      cancelled = true
    }
  }, [callShortId, wantStereo, tracks.length, decodeAndSetTracks])

  useEffect(() => {
    repaint()
  }, [tracks, duration, showSkeleton, showStereoLayout, repaint])

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
      if (audio && duration > 0) {
        paintStateRef.current.progressRatio = audio.currentTime / duration
        repaint()
        if (now - lastUiUpdate > 250) {
          setCurrentTime(audio.currentTime)
          lastUiUpdate = now
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, duration, repaint])

  const seekFromClientX = (clientX: number) => {
    const container = containerRef.current
    const audio = audioRef.current
    if (!container || !audio || !duration) return
    const rect = container.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    audio.currentTime = ratio * duration
    setCurrentTime(audio.currentTime)
    paintStateRef.current.progressRatio = ratio
    repaint()
  }

  const togglePlay = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (playing) {
      audio.pause()
      return
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

  if (!callRecordingId && !callShortId && !evaluatorResultId) return null

  const canPlay = Boolean(audioUrl) && !fetching
  const canSeek = canPlay && duration > 0

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Recording</p>
        <span className="font-mono text-xs tabular-nums text-gray-600">
          {formatClock(currentTime)} / {formatClock(duration)}
        </span>
      </div>

      <div className="px-3 pt-3">
        {showStereoLayout ? (
          <div className="mb-2 flex gap-5 px-1 text-[10px] font-semibold uppercase tracking-wider">
            <span className="text-orange-500">User</span>
            <span className="text-teal-500">Assistant</span>
          </div>
        ) : null}

        {fetching && !audioUrl ? (
          <div className="flex h-36 items-center justify-center gap-2 text-sm text-gray-500">
            <Loader className="h-4 w-4 animate-spin" />
            Loading audio…
          </div>
        ) : loadError && !audioUrl ? (
          <div className="flex h-36 items-center justify-center px-4 text-center text-sm text-amber-700">
            {loadError}
          </div>
        ) : (
          <div className="relative">
            <div
              ref={containerRef}
              className={`relative select-none rounded-lg ${canSeek ? 'cursor-pointer' : 'cursor-default'}`}
              onMouseDown={(e) => {
                if (!canSeek) return
                draggingRef.current = true
                seekFromClientX(e.clientX)
              }}
              onMouseMove={(e) => {
                if (draggingRef.current) seekFromClientX(e.clientX)
              }}
              onMouseUp={() => {
                draggingRef.current = false
              }}
              onMouseLeave={() => {
                draggingRef.current = false
              }}
            >
              <canvas ref={canvasRef} className="block w-full rounded-lg" />
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-gray-100 px-4 py-3">
        <button
          type="button"
          onClick={() => void togglePlay()}
          disabled={!canPlay}
          className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-primary-400 text-primary-900 shadow-md shadow-primary-200/80 hover:bg-primary-300 disabled:opacity-40"
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

      {audioUrl ? (
        <audio
          ref={audioRef}
          src={audioUrl}
          preload="auto"
          className="hidden"
          onLoadedMetadata={(e) => {
            const nextDuration = e.currentTarget?.duration
            if (typeof nextDuration === 'number' && Number.isFinite(nextDuration) && nextDuration > 0) {
              setDuration((prev) => (prev > 0 ? prev : nextDuration))
            }
          }}
          onEnded={() => setPlaying(false)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      ) : null}
    </div>
  )
}
