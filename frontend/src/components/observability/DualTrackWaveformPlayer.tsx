import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { Bot, Loader, Pause, Play, User } from 'lucide-react'
import {
  formatPlaybackTime,
  loadAudioPeaks,
  peaksForTimeRange,
  buildSyntheticPeaks,
  type AudioPeakData,
} from '../../lib/audioWaveform'
import {
  findSegmentIndexAtTime,
  type WaveformSegment,
  type WaveformSpeaker,
} from './waveformSegments'

const SPEAKER_COLORS: Record<
  WaveformSpeaker,
  { stroke: string; fill: string; activeFill: string }
> = {
  agent: {
    stroke: '#16a34a',
    fill: 'rgba(34, 197, 94, 0.55)',
    activeFill: 'rgba(34, 197, 94, 0.85)',
  },
  user: {
    stroke: '#2563eb',
    fill: 'rgba(59, 130, 246, 0.55)',
    activeFill: 'rgba(59, 130, 246, 0.85)',
  },
}

const SPEED_OPTIONS = [0.75, 1, 1.25, 1.5, 2]

function drawSegmentWaveform(
  ctx: CanvasRenderingContext2D,
  x: number,
  width: number,
  height: number,
  segmentPeaks: Float32Array,
  colors: { stroke: string; fill: string },
  active: boolean,
) {
  if (width < 2) return
  const midY = height / 2
  const radius = 6
  const left = x
  const right = x + width
  const top = 4
  const bottom = height - 4
  const innerH = bottom - top

  ctx.beginPath()
  ctx.moveTo(left + radius, top)
  ctx.lineTo(right - radius, top)
  ctx.quadraticCurveTo(right, top, right, top + radius)
  ctx.lineTo(right, bottom - radius)
  ctx.quadraticCurveTo(right, bottom, right - radius, bottom)
  ctx.lineTo(left + radius, bottom)
  ctx.quadraticCurveTo(left, bottom, left, bottom - radius)
  ctx.lineTo(left, top + radius)
  ctx.quadraticCurveTo(left, top, left + radius, top)
  ctx.closePath()
  ctx.fillStyle = active ? colors.fill.replace('0.55', '0.85') : colors.fill
  ctx.fill()

  if (segmentPeaks.length === 0) return

  const barWidth = Math.max(1, width / segmentPeaks.length)
  ctx.fillStyle = active ? '#ffffff' : colors.stroke
  ctx.globalAlpha = active ? 0.95 : 0.75

  for (let i = 0; i < segmentPeaks.length; i += 1) {
    const amp = Math.max(0.08, segmentPeaks[i])
    const barH = amp * innerH * 0.9
    const bx = left + i * barWidth + barWidth * 0.15
    const bw = Math.max(1, barWidth * 0.7)
    ctx.fillRect(bx, midY - barH / 2, bw, barH)
  }
  ctx.globalAlpha = 1
}

function TrackCanvas({
  speaker,
  label,
  icon,
  segments,
  peakData,
  durationSec,
  currentTimeSec,
  activeSegmentIndex,
  onSeek,
  onSegmentClick,
}: {
  speaker: WaveformSpeaker
  label: string
  icon: ReactNode
  segments: WaveformSegment[]
  peakData: AudioPeakData
  durationSec: number
  currentTimeSec: number
  activeSegmentIndex: number | null
  onSeek: (timeSec: number) => void
  onSegmentClick: (segmentIndex: number, startSec: number) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const speakerSegments = useMemo(
    () => segments.filter((seg) => seg.speaker === speaker),
    [segments, speaker],
  )

  const globalIndexBySpeakerIndex = useMemo(() => {
    return speakerSegments.map((seg) => segments.indexOf(seg))
  }, [segments, speakerSegments])

  const redraw = useCallback(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container || durationSec <= 0) return

    const width = container.clientWidth
    const height = 52
    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)

    ctx.strokeStyle = '#e5e7eb'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, height / 2)
    ctx.lineTo(width, height / 2)
    ctx.stroke()

    const colors = SPEAKER_COLORS[speaker]
    speakerSegments.forEach((seg, speakerIdx) => {
      const globalIdx = globalIndexBySpeakerIndex[speakerIdx]
      const x = (seg.startSec / durationSec) * width
      const segWidth = Math.max(4, ((seg.endSec - seg.startSec) / durationSec) * width)
      const segPeaks = peaksForTimeRange(
        peakData.peaks,
        peakData.durationSec,
        seg.startSec,
        seg.endSec,
        Math.max(12, Math.floor(segWidth / 3)),
      )
      drawSegmentWaveform(
        ctx,
        x,
        segWidth,
        height,
        segPeaks,
        colors,
        activeSegmentIndex === globalIdx,
      )
    })

    const playheadX = (currentTimeSec / durationSec) * width
    ctx.strokeStyle = '#ef4444'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(playheadX, 0)
    ctx.lineTo(playheadX, height)
    ctx.stroke()
  }, [
    activeSegmentIndex,
    currentTimeSec,
    durationSec,
    globalIndexBySpeakerIndex,
    peakData,
    speaker,
    speakerSegments,
  ])

  useEffect(() => {
    redraw()
  }, [redraw])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(() => redraw())
    observer.observe(container)
    return () => observer.disconnect()
  }, [redraw])

  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    const timeSec = ratio * durationSec

    const clickedSpeakerIdx = speakerSegments.findIndex(
      (seg) => timeSec >= seg.startSec && timeSec <= seg.endSec,
    )
    if (clickedSpeakerIdx >= 0) {
      const globalIdx = globalIndexBySpeakerIndex[clickedSpeakerIdx]
      onSegmentClick(globalIdx, speakerSegments[clickedSpeakerIdx].startSec)
    } else {
      onSeek(timeSec)
    }
  }

  return (
    <div className="flex items-stretch gap-3 min-h-[52px]">
      <div className="w-28 shrink-0 flex items-center gap-2 text-xs font-medium text-gray-700 pt-3">
        <span className="text-base leading-none">{icon}</span>
        <span className="truncate">{label}</span>
      </div>
      <div ref={containerRef} className="flex-1 min-w-0 cursor-pointer py-1" onClick={handleClick}>
        <canvas ref={canvasRef} className="block w-full rounded-md" />
      </div>
    </div>
  )
}

export interface DualTrackWaveformPlayerHandle {
  seek: (timeSec: number) => void
  play: () => void
  pause: () => void
}

export interface DualTrackWaveformPlayerProps {
  audioUrl: string
  segments: WaveformSegment[]
  agentLabel?: string
  userLabel?: string
  activeSegmentIndex?: number | null
  fallbackDurationSec?: number | null
  liveMode?: boolean
  liveDurationSec?: number | null
  onTimeUpdate?: (timeSec: number) => void
  onSegmentActive?: (segmentIndex: number | null) => void
  onSegmentClick?: (segmentIndex: number, startSec: number) => void
}

const DualTrackWaveformPlayer = forwardRef<DualTrackWaveformPlayerHandle, DualTrackWaveformPlayerProps>(
  function DualTrackWaveformPlayer(
    {
      audioUrl,
      segments,
      agentLabel = 'Agent',
      userLabel = 'Customer',
      activeSegmentIndex = null,
      fallbackDurationSec = null,
      liveMode = false,
      liveDurationSec = null,
      onTimeUpdate,
      onSegmentActive,
      onSegmentClick,
    },
    ref,
  ) {
    const audioRef = useRef<HTMLAudioElement>(null)
    const [peakData, setPeakData] = useState<AudioPeakData | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [isPlaying, setIsPlaying] = useState(false)
    const [audioReady, setAudioReady] = useState(false)
    const [playbackError, setPlaybackError] = useState<string | null>(null)
    const [currentTimeSec, setCurrentTimeSec] = useState(0)
    const [mediaDurationSec, setMediaDurationSec] = useState(0)
    const [playbackRate, setPlaybackRate] = useState(1)

    const durationSec =
      mediaDurationSec > 0
        ? mediaDurationSec
        : liveDurationSec && liveDurationSec > 0
          ? liveDurationSec
          : (peakData?.durationSec ?? 0)

    const estimateSegmentDuration = useCallback(() => {
      const lastSeg = segments[segments.length - 1]
      return (
        fallbackDurationSec ??
        liveDurationSec ??
        lastSeg?.endSec ??
        segments.reduce((max, s) => Math.max(max, s.endSec), 0) ??
        60
      )
    }, [fallbackDurationSec, liveDurationSec, segments])

    useEffect(() => {
      let cancelled = false

      if (liveMode) {
        const duration = Math.max(estimateSegmentDuration(), 1)
        setPeakData(buildSyntheticPeaks(duration))
        setLoading(false)
        setError(null)
        return () => {
          cancelled = true
        }
      }

      setLoading(true)
      setError(null)
      loadAudioPeaks(audioUrl)
        .then((data) => {
          if (!cancelled) {
            setPeakData(data)
            setLoading(false)
          }
        })
        .catch(() => {
          if (!cancelled) {
            setPeakData(buildSyntheticPeaks(Math.max(estimateSegmentDuration(), 1)))
            setError(null)
            setLoading(false)
          }
        })
      return () => {
        cancelled = true
      }
    }, [audioUrl, estimateSegmentDuration, liveMode])

    const playAudio = useCallback(async () => {
      const audio = audioRef.current
      if (!audio) return
      setPlaybackError(null)
      try {
        await audio.play()
      } catch {
        setPlaybackError('Could not start playback. The recording may still be loading.')
      }
    }, [])

    useEffect(() => {
      const audio = audioRef.current
      if (!audio || !audioUrl) return

      if (liveMode) {
        const wasPlaying = !audio.paused
        const prevTime = audio.currentTime
        if (audio.src !== audioUrl) {
          audio.src = audioUrl
        }
        const onReady = () => {
          if (Number.isFinite(audio.duration) && audio.duration > 0) {
            setMediaDurationSec(audio.duration)
          } else if (liveDurationSec && liveDurationSec > 0) {
            setMediaDurationSec(liveDurationSec)
          }
          setAudioReady(true)
          setPlaybackError(null)
          if (Number.isFinite(prevTime) && prevTime > 0) {
            const cap = audio.duration > 0 ? audio.duration : prevTime
            audio.currentTime = Math.min(prevTime, cap)
            setCurrentTimeSec(audio.currentTime)
          }
          if (wasPlaying) void playAudio()
        }
        audio.addEventListener('loadedmetadata', onReady, { once: true })
        audio.load()
        return () => audio.removeEventListener('loadedmetadata', onReady)
      }

      setAudioReady(false)
      setIsPlaying(false)
      setPlaybackError(null)
      setCurrentTimeSec(0)
      setMediaDurationSec(0)

      if (audio.src !== audioUrl) {
        audio.src = audioUrl
      }
      audio.load()
    }, [audioUrl, liveDurationSec, liveMode, playAudio])

    const seek = useCallback(
      (timeSec: number) => {
        const audio = audioRef.current
        if (!audio || durationSec <= 0) return
        audio.currentTime = Math.min(durationSec, Math.max(0, timeSec))
        setCurrentTimeSec(audio.currentTime)
        onTimeUpdate?.(audio.currentTime)
        const idx = findSegmentIndexAtTime(segments, audio.currentTime)
        onSegmentActive?.(idx)
      },
      [durationSec, onSegmentActive, onTimeUpdate, segments],
    )

    useImperativeHandle(
      ref,
      () => ({
        seek,
        play: () => {
          void playAudio()
        },
        pause: () => audioRef.current?.pause(),
      }),
      [playAudio, seek],
    )

    useEffect(() => {
      const audio = audioRef.current
      if (!audio) return
      audio.playbackRate = playbackRate
    }, [playbackRate])

    const togglePlay = () => {
      const audio = audioRef.current
      if (!audio || !audioReady) return
      if (audio.paused) void playAudio()
      else audio.pause()
    }

    const handleTimeUpdate = () => {
      const audio = audioRef.current
      if (!audio) return
      setCurrentTimeSec(audio.currentTime)
      onTimeUpdate?.(audio.currentTime)
      const idx = findSegmentIndexAtTime(segments, audio.currentTime)
      onSegmentActive?.(idx)
    }

    const handleLoadedMetadata = () => {
      const audio = audioRef.current
      if (!audio) return
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        setMediaDurationSec(audio.duration)
      }
      setAudioReady(true)
      setPlaybackError(null)
    }

    const handleSegmentClick = (segmentIndex: number, startSec: number) => {
      seek(startSec)
      onSegmentClick?.(segmentIndex, startSec)
      void playAudio()
    }

    if (loading) {
      return (
        <div className="rounded-xl border border-gray-100 bg-white px-4 py-6 flex items-center gap-2 text-sm text-gray-500">
          <Loader className="w-4 h-4 animate-spin text-indigo-500" />
          Loading waveform…
        </div>
      )
    }

    if (error || !peakData) {
      return (
        <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-xs text-amber-800">
          Could not render waveform. Using basic audio controls.
          <audio ref={audioRef} controls src={audioUrl} className="w-full mt-2" preload="metadata" />
        </div>
      )
    }

    return (
      <div className="rounded-xl border border-gray-100 bg-white shadow-sm overflow-hidden">
        <audio
          ref={audioRef}
          preload="auto"
          playsInline
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onCanPlay={() => setAudioReady(true)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
          onError={() => {
            setAudioReady(false)
            setPlaybackError('Failed to load recording audio.')
          }}
        />

        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={togglePlay}
              disabled={!audioReady}
              className="w-9 h-9 rounded-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed text-white flex items-center justify-center shadow-sm transition-colors"
              aria-label={isPlaying ? 'Pause' : 'Play'}
            >
              {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
            </button>
            <span className="text-sm font-medium text-gray-800 tabular-nums">
              {formatPlaybackTime(currentTimeSec)} / {formatPlaybackTime(durationSec)}
            </span>
            {liveMode && (
              <span className="text-[10px] font-semibold uppercase tracking-wide text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full">
                Live
              </span>
            )}
            {!audioReady && (
              <span className="text-xs text-gray-400">{liveMode ? 'Buffering…' : 'Loading audio…'}</span>
            )}
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-600">
            Speed:
            <select
              value={playbackRate}
              onChange={(e) => setPlaybackRate(Number(e.target.value))}
              className="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white"
            >
              {SPEED_OPTIONS.map((speed) => (
                <option key={speed} value={speed}>
                  {speed}x
                </option>
              ))}
            </select>
          </label>
        </div>

        {playbackError && (
          <p className="px-4 py-2 text-xs text-amber-700 bg-amber-50 border-b border-amber-100">
            {playbackError}
          </p>
        )}

        <div className="px-4 py-3 space-y-1 bg-gradient-to-b from-gray-50/80 to-white">
          <TrackCanvas
            speaker="agent"
            label={agentLabel}
            icon={<Bot className="w-4 h-4 text-green-600" />}
            segments={segments}
            peakData={peakData}
            durationSec={durationSec}
            currentTimeSec={currentTimeSec}
            activeSegmentIndex={activeSegmentIndex}
            onSeek={seek}
            onSegmentClick={handleSegmentClick}
          />
          <TrackCanvas
            speaker="user"
            label={userLabel}
            icon={<User className="w-4 h-4 text-blue-600" />}
            segments={segments}
            peakData={peakData}
            durationSec={durationSec}
            currentTimeSec={currentTimeSec}
            activeSegmentIndex={activeSegmentIndex}
            onSeek={seek}
            onSegmentClick={handleSegmentClick}
          />
        </div>
      </div>
    )
  },
)

export default DualTrackWaveformPlayer
