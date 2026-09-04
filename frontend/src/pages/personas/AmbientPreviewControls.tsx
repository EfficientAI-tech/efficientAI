import { Loader2, Pause, Play, Volume2 } from 'lucide-react'
import { formatPlaybackTime, formatPreviewVolume } from './useAmbientPreview'

interface AmbientPreviewControlsProps {
  previewId: string
  onToggle: () => void
  currentTime: number
  duration: number
  onSeek: (time: number) => void
  volume: number
  onVolumeChange: (volume: number) => void
  isPlaying: boolean
  isLoading: boolean
  isActive: boolean
  disabled?: boolean
  compact?: boolean
}

export default function AmbientPreviewControls({
  previewId,
  onToggle,
  currentTime,
  duration,
  onSeek,
  volume,
  onVolumeChange,
  isPlaying,
  isLoading,
  isActive,
  disabled = false,
  compact = false,
}: AmbientPreviewControlsProps) {
  const canSeek = isActive && duration > 0 && !isLoading

  return (
    <div className={compact ? 'space-y-1.5' : 'rounded-md border border-gray-200 bg-gray-50/70 p-2 space-y-1.5'}>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={disabled || isLoading}
          onClick={onToggle}
          aria-label={isPlaying ? `Stop preview ${previewId}` : `Play preview ${previewId}`}
          className="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white p-1.5 text-gray-700 hover:bg-gray-50 disabled:opacity-50 shrink-0"
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : isPlaying ? (
            <Pause className="h-3.5 w-3.5" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
        </button>
        <input
          type="range"
          min={0}
          max={duration > 0 ? duration : 1}
          step={0.1}
          value={canSeek ? currentTime : 0}
          disabled={disabled || !canSeek}
          onChange={(e) => onSeek(Number(e.target.value))}
          className="flex-1 min-w-0 h-1 accent-primary-600 disabled:opacity-40"
          aria-label="Playback position"
        />
        <span className="text-[10px] tabular-nums text-gray-500 w-[4.5rem] text-right shrink-0">
          {formatPlaybackTime(canSeek ? currentTime : 0)} / {formatPlaybackTime(duration)}
        </span>
      </div>

      <div className="flex items-center gap-1.5 pl-7">
        <Volume2 className="h-3 w-3 text-gray-400 shrink-0" aria-hidden />
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={volume}
          disabled={disabled}
          onChange={(e) => onVolumeChange(Number(e.target.value))}
          className="flex-1 min-w-0 h-1 accent-primary-600"
          aria-label="Preview volume"
        />
        <span className="text-[10px] tabular-nums text-gray-500 w-8 text-right shrink-0">
          {formatPreviewVolume(volume)}
        </span>
      </div>
    </div>
  )
}
