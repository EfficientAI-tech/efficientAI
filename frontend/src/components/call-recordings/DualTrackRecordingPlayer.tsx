import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Download, Loader, Pause, Play, Volume2 } from 'lucide-react'
import {
  buildEnvelopeFromSegments,
  decodeAudioEnvelope,
  fetchAudioArrayBuffer,
  formatPlaybackTime,
  isUserSpeakerLabel,
  type ChannelEnvelope,
  type SpeakerSegmentLike,
} from '../../lib/audioWaveform'
import type { RecordingDownloadTrack } from '../../hooks/useRecordingDownloadTracks'

export type DualTrackRecordingPlayerProps = {
  audioUrl: string
  waveformAudioUrl?: string | null
  speakerSegments?: SpeakerSegmentLike[] | null
  recordingFormat?: string | null
  downloadTracks?: RecordingDownloadTrack[]
  downloadTracksLoading?: boolean
  userLabel?: string
  agentLabel?: string
  compact?: boolean
  className?: string
  onTimeUpdate?: (currentTime: number) => void
  onSeek?: (time: number) => void
  seekToTime?: number | null
  onSeekToTimeHandled?: () => void
}

type TrackLaneProps = {
  label: string
  buckets: number[]
  colorClass: string
  bgClass: string
  duration: number
  currentTime: number
  segmentRegions?: Array<{ start: number; end: number }>
  segmentClass?: string
  onSeek: (time: number) => void
}

function TrackLane({
  label,
  buckets,
  colorClass,
  bgClass,
  duration,
  currentTime,
  segmentRegions,
  segmentClass,
  onSeek,
}: TrackLaneProps) {
  const laneRef = useRef<HTMLDivElement>(null)

  const seekFromClientX = useCallback(
    (clientX: number) => {
      const lane = laneRef.current
      if (!lane || duration <= 0) return
      const rect = lane.getBoundingClientRect()
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
      onSeek(ratio * duration)
    },
    [duration, onSeek],
  )

  const playheadPct = duration > 0 ? (currentTime / duration) * 100 : 0

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-gray-500">
        <span>{label}</span>
      </div>
      <div
        ref={laneRef}
        className={`relative h-12 rounded-md border border-gray-200 ${bgClass} overflow-hidden cursor-pointer`}
        onClick={(event) => seekFromClientX(event.clientX)}
        role="slider"
        aria-label={`${label} activity timeline`}
        aria-valuemin={0}
        aria-valuemax={duration}
        aria-valuenow={currentTime}
        tabIndex={0}
        onKeyDown={(event) => {
          if (duration <= 0) return
          const step = event.shiftKey ? 5 : 1
          if (event.key === 'ArrowRight') {
            event.preventDefault()
            onSeek(Math.min(duration, currentTime + step))
          } else if (event.key === 'ArrowLeft') {
            event.preventDefault()
            onSeek(Math.max(0, currentTime - step))
          }
        }}
      >
        {segmentRegions?.map((region, index) => {
          const left = duration > 0 ? (region.start / duration) * 100 : 0
          const width = duration > 0 ? ((region.end - region.start) / duration) * 100 : 0
          return (
            <div
              key={`${region.start}-${region.end}-${index}`}
              className={`absolute inset-y-1 rounded-sm opacity-30 ${segmentClass || ''}`}
              style={{ left: `${left}%`, width: `${Math.max(width, 0.4)}%` }}
            />
          )
        })}

        <div className="absolute inset-x-1 inset-y-1 flex items-end gap-px">
          {buckets.map((value, index) => (
            <div
              key={index}
              className={`flex-1 min-w-0 rounded-[1px] ${colorClass}`}
              style={{ height: `${Math.max(8, value * 100)}%`, opacity: value > 0.04 ? 0.95 : 0.15 }}
            />
          ))}
        </div>

        <div
          className="absolute inset-y-0 w-0.5 bg-gray-900/80 pointer-events-none"
          style={{ left: `calc(${playheadPct}% - 1px)` }}
        />
      </div>
    </div>
  )
}

export default function DualTrackRecordingPlayer({
  audioUrl,
  waveformAudioUrl = null,
  speakerSegments: speakerSegmentsProp = [],
  recordingFormat,
  downloadTracks = [],
  downloadTracksLoading = false,
  userLabel = 'You',
  agentLabel = 'Agent',
  compact = false,
  className = '',
  onTimeUpdate,
  onSeek,
  seekToTime = null,
  onSeekToTimeHandled,
}: DualTrackRecordingPlayerProps) {
  const speakerSegments = speakerSegmentsProp ?? []
  const audioRef = useRef<HTMLAudioElement>(null)
  const [envelope, setEnvelope] = useState<ChannelEnvelope | null>(null)
  const [loadingWaveform, setLoadingWaveform] = useState(false)
  const [waveformError, setWaveformError] = useState<string | null>(null)
  const [decodeFailed, setDecodeFailed] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackError, setPlaybackError] = useState<string | null>(null)
  const [showDownloadMenu, setShowDownloadMenu] = useState(false)

  const decodeSourceUrl = waveformAudioUrl || audioUrl

  const isStereo =
    (recordingFormat || '').toLowerCase() === 'stereo' || (envelope?.numChannels ?? 0) >= 2

  useEffect(() => {
    let cancelled = false
    if (!decodeSourceUrl) return undefined

    setLoadingWaveform(true)
    setWaveformError(null)
    setDecodeFailed(false)
    setEnvelope(null)

    async function loadWaveform() {
      try {
        const buffer = await fetchAudioArrayBuffer(decodeSourceUrl)
        const decoded = await decodeAudioEnvelope(buffer)
        if (!cancelled) {
          setEnvelope(decoded)
          setDuration((current) => current || decoded.duration)
        }
      } catch {
        if (!cancelled) {
          setDecodeFailed(true)
        }
      } finally {
        if (!cancelled) {
          setLoadingWaveform(false)
        }
      }
    }

    void loadWaveform()
    return () => {
      cancelled = true
    }
  }, [decodeSourceUrl])

  useEffect(() => {
    if (envelope || loadingWaveform) return

    const effectiveDuration = duration || 0
    if (effectiveDuration <= 0 || speakerSegments.length === 0) {
      if (decodeFailed) {
        setWaveformError('Could not render activity waveform')
      }
      return
    }

    setEnvelope(buildEnvelopeFromSegments(speakerSegments, effectiveDuration))
    setWaveformError(null)
  }, [decodeFailed, duration, envelope, loadingWaveform, speakerSegments])

  const userBuckets = useMemo(() => {
    if (envelope) return envelope.user
    return []
  }, [envelope])

  const agentBuckets = useMemo(() => {
    if (envelope) return envelope.agent
    return []
  }, [envelope])

  const userRegions = useMemo(
    () =>
      speakerSegments
        .filter((segment) => isUserSpeakerLabel(segment.speaker))
        .map((segment) => ({ start: segment.start, end: segment.end })),
    [speakerSegments],
  )

  const agentRegions = useMemo(
    () =>
      speakerSegments
        .filter((segment) => !isUserSpeakerLabel(segment.speaker))
        .map((segment) => ({ start: segment.start, end: segment.end })),
    [speakerSegments],
  )

  const seekTo = useCallback(
    (time: number) => {
      const audio = audioRef.current
      if (!audio) return
      const clamped = Math.max(0, Math.min(duration || audio.duration || 0, time))
      audio.currentTime = clamped
      setCurrentTime(clamped)
      onSeek?.(clamped)
    },
    [duration, onSeek],
  )

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current
    if (!audio || !audioUrl) return
    setPlaybackError(null)
    if (audio.paused) {
      try {
        await audio.play()
      } catch {
        setPlaybackError('Playback failed. Try pressing play again.')
      }
    } else {
      audio.pause()
    }
  }, [audioUrl])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !audioUrl) return

    audio.load()
    setCurrentTime(0)
    setIsPlaying(false)
    setPlaybackError(null)

    const syncDuration = () => {
      if (audio.duration && Number.isFinite(audio.duration)) {
        setDuration(audio.duration)
      }
    }

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      onTimeUpdate?.(audio.currentTime)
    }
    const handlePlay = () => setIsPlaying(true)
    const handlePause = () => setIsPlaying(false)
    const handleEnded = () => setIsPlaying(false)

    syncDuration()
    audio.addEventListener('loadedmetadata', syncDuration)
    audio.addEventListener('durationchange', syncDuration)
    audio.addEventListener('canplay', syncDuration)
    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('play', handlePlay)
    audio.addEventListener('pause', handlePause)
    audio.addEventListener('ended', handleEnded)

    return () => {
      audio.removeEventListener('loadedmetadata', syncDuration)
      audio.removeEventListener('durationchange', syncDuration)
      audio.removeEventListener('canplay', syncDuration)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('ended', handleEnded)
    }
  }, [audioUrl, onTimeUpdate])

  useEffect(() => {
    if (seekToTime == null || !Number.isFinite(seekToTime)) return
    seekTo(seekToTime)
    const audio = audioRef.current
    if (audio) {
      void audio.play().catch(() => undefined)
    }
    onSeekToTimeHandled?.()
  }, [seekToTime, onSeekToTimeHandled, seekTo])

  const effectiveDuration = duration || envelope?.duration || 0
  const availableDownloads =
    downloadTracks.length > 0
      ? downloadTracks
      : [{ id: 'primary', label: 'Recording', url: audioUrl }]

  const primaryDownload = availableDownloads[0]
  const showDownloadMenuButton = downloadTracksLoading || availableDownloads.length > 1

  return (
    <div className={`rounded-xl border border-gray-200 bg-white ${compact ? 'p-3' : 'p-4'} space-y-3 ${className}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Volume2 className="h-4 w-4 text-indigo-500 flex-shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900">Call recording</p>
            {!compact && (
              <p className="text-[11px] text-gray-500 truncate">
                {isStereo
                  ? 'Stereo lanes: you (top) · agent (bottom)'
                  : decodeFailed && speakerSegments.length > 0
                    ? 'Activity from transcript timing'
                    : 'Dual-track activity timeline'}
              </p>
            )}
          </div>
        </div>
        <div className="relative flex-shrink-0">
          {showDownloadMenuButton ? (
            <>
              <button
                type="button"
                onClick={() => setShowDownloadMenu((open) => !open)}
                disabled={downloadTracksLoading && availableDownloads.length <= 1}
                className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:text-indigo-600 hover:border-indigo-200 disabled:opacity-60"
              >
                {downloadTracksLoading ? (
                  <Loader className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Download
                <ChevronDown className="h-3 w-3" />
              </button>
              {showDownloadMenu && availableDownloads.length > 0 && (
                <div className="absolute right-0 z-20 mt-1 min-w-[180px] rounded-md border border-gray-200 bg-white py-1 shadow-lg">
                  {availableDownloads.map((track) => (
                    <a
                      key={track.id}
                      href={track.url}
                      download
                      className="block px-3 py-1.5 text-xs text-gray-700 hover:bg-indigo-50 hover:text-indigo-700"
                      onClick={() => setShowDownloadMenu(false)}
                    >
                      {track.label}
                    </a>
                  ))}
                </div>
              )}
            </>
          ) : (
            <a
              href={primaryDownload.url}
              download
              className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:text-indigo-600 hover:border-indigo-200"
            >
              <Download className="h-3.5 w-3.5" />
              Download
            </a>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void togglePlayback()}
          disabled={!audioUrl}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-700 transition-colors disabled:opacity-50"
          aria-label={isPlaying ? 'Pause recording' : 'Play recording'}
        >
          {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
        </button>
        <div className="text-xs tabular-nums text-gray-600">
          {formatPlaybackTime(currentTime)} / {formatPlaybackTime(effectiveDuration)}
        </div>
        {loadingWaveform && (
          <div className="ml-auto flex items-center gap-1.5 text-xs text-gray-400">
            <Loader className="h-3.5 w-3.5 animate-spin" />
            Loading waveform
          </div>
        )}
      </div>

      {playbackError ? (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-md px-3 py-2">
          {playbackError}
        </p>
      ) : null}

      {waveformError && userBuckets.length === 0 ? (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-md px-3 py-2">
          {waveformError}. Basic playback is still available below.
        </p>
      ) : userBuckets.length > 0 ? (
        <div className="space-y-2">
          {waveformError && decodeFailed && speakerSegments.length > 0 ? (
            <p className="text-[11px] text-gray-500">
              Waveform decoded from transcript timing because audio analysis was unavailable.
            </p>
          ) : null}
          <TrackLane
            label={userLabel}
            buckets={userBuckets}
            colorClass="bg-indigo-500"
            bgClass="bg-indigo-50/70"
            duration={effectiveDuration}
            currentTime={currentTime}
            segmentRegions={!isStereo ? userRegions : undefined}
            segmentClass="bg-indigo-400"
            onSeek={seekTo}
          />
          <TrackLane
            label={agentLabel}
            buckets={agentBuckets}
            colorClass="bg-emerald-500"
            bgClass="bg-emerald-50/70"
            duration={effectiveDuration}
            currentTime={currentTime}
            segmentRegions={!isStereo ? agentRegions : undefined}
            segmentClass="bg-emerald-400"
            onSeek={seekTo}
          />
          <div className="flex justify-between text-[10px] tabular-nums text-gray-400 px-0.5">
            <span>0:00</span>
            {effectiveDuration >= 120 && <span>{formatPlaybackTime(effectiveDuration / 2)}</span>}
            <span>{formatPlaybackTime(effectiveDuration)}</span>
          </div>
        </div>
      ) : null}

      <audio ref={audioRef} key={audioUrl} src={audioUrl} preload="auto" className="sr-only" />
    </div>
  )
}
