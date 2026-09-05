import { Download, Loader2, Pause, Play, Volume2 } from 'lucide-react'
import type { Ref } from 'react'

import {
  formatRecordingTime,
  formatVolumePercent,
  PLAYBACK_RATES,
  type PlaybackRate,
  useRecordingAudioPlayer,
} from '../../hooks/useRecordingAudioPlayer'

const SLIDER_CLASS =
  'flex-1 min-w-0 h-2 rounded-full appearance-none bg-gray-200 accent-primary-600 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary-600 [&::-webkit-slider-thumb]:shadow [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-primary-600'

interface RecordingAudioPlayerProps {
  src: string
  downloadUrl?: string
  audioRef?: Ref<HTMLAudioElement | null>
  onTimeUpdate?: (currentTime: number) => void
  onLoadedMetadata?: (duration: number) => void
  onEnded?: () => void
  className?: string
}

export default function RecordingAudioPlayer({
  src,
  downloadUrl,
  audioRef,
  onTimeUpdate,
  onLoadedMetadata,
  onEnded,
  className = '',
}: RecordingAudioPlayerProps) {
  const {
    setAudioElementRef,
    isPlaying,
    isLoading,
    currentTime,
    duration,
    volume,
    playbackRate,
    togglePlay,
    seek,
    setVolume,
    setPlaybackRate,
    canSeek,
  } = useRecordingAudioPlayer({
    src,
    audioRef,
    onTimeUpdate,
    onLoadedMetadata,
    onEnded,
  })

  return (
    <div className={`rounded-xl border border-gray-200 bg-gray-50/80 p-4 space-y-3 ${className}`}>
      <audio ref={setAudioElementRef} src={src} preload="metadata" className="hidden" />

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void togglePlay()}
          disabled={!src || isLoading}
          aria-label={isPlaying ? 'Pause recording' : 'Play recording'}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-gray-300 bg-white text-gray-800 shadow-sm hover:bg-gray-50 disabled:opacity-50"
        >
          {isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : isPlaying ? (
            <Pause className="h-5 w-5" />
          ) : (
            <Play className="h-5 w-5 ml-0.5" />
          )}
        </button>

        <input
          type="range"
          min={0}
          max={duration > 0 ? duration : 1}
          step={0.1}
          value={canSeek ? currentTime : 0}
          disabled={!canSeek}
          onChange={(e) => seek(Number(e.target.value))}
          className={SLIDER_CLASS}
          aria-label="Recording position"
        />

        <span className="w-24 shrink-0 text-right text-sm tabular-nums text-gray-600">
          {formatRecordingTime(canSeek ? currentTime : 0)} / {formatRecordingTime(duration)}
        </span>

        {downloadUrl ? (
          <a
            href={downloadUrl}
            download
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-gray-300 bg-white text-gray-500 hover:text-indigo-600 hover:bg-indigo-50"
            aria-label="Download recording"
          >
            <Download className="h-4 w-4" />
          </a>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3 pl-14">
        <div className="flex min-w-[220px] flex-1 items-center gap-2">
          <Volume2 className="h-4 w-4 shrink-0 text-gray-400" aria-hidden />
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={volume}
            onChange={(e) => setVolume(Number(e.target.value))}
            className={SLIDER_CLASS}
            aria-label="Volume"
          />
          <span className="w-10 shrink-0 text-right text-xs tabular-nums text-gray-500">
            {formatVolumePercent(volume)}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">Speed</span>
          {PLAYBACK_RATES.map((rate) => (
            <button
              key={rate}
              type="button"
              onClick={() => setPlaybackRate(rate as PlaybackRate)}
              className={`rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
                playbackRate === rate
                  ? 'border-primary-600 bg-primary-50 text-primary-700'
                  : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              {rate}x
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
