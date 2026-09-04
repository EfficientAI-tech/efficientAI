import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
  type Ref,
} from 'react'

export const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2] as const
export type PlaybackRate = (typeof PLAYBACK_RATES)[number]

const DEFAULT_VOLUME = 0.85

export function formatRecordingTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function formatVolumePercent(volume: number): string {
  return `${Math.round(volume * 100)}%`
}

interface UseRecordingAudioPlayerOptions {
  src?: string | null
  audioRef?: Ref<HTMLAudioElement | null>
  onTimeUpdate?: (currentTime: number) => void
  onLoadedMetadata?: (duration: number) => void
  onEnded?: () => void
}

function assignAudioRef(
  ref: Ref<HTMLAudioElement | null> | undefined,
  element: HTMLAudioElement | null,
) {
  if (!ref) return
  if (typeof ref === 'function') {
    ref(element)
    return
  }
  ;(ref as MutableRefObject<HTMLAudioElement | null>).current = element
}

export function useRecordingAudioPlayer({
  src,
  audioRef,
  onTimeUpdate,
  onLoadedMetadata,
  onEnded,
}: UseRecordingAudioPlayerOptions) {
  const internalRef = useRef<HTMLAudioElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolumeState] = useState(DEFAULT_VOLUME)
  const [playbackRate, setPlaybackRateState] = useState<PlaybackRate>(1)

  const setAudioElementRef = useCallback(
    (element: HTMLAudioElement | null) => {
      internalRef.current = element
      assignAudioRef(audioRef, element)
    },
    [audioRef],
  )

  const getAudio = useCallback(() => internalRef.current, [])

  const togglePlay = useCallback(async () => {
    const audio = internalRef.current
    if (!audio || !src) return

    if (audio.paused) {
      setIsLoading(true)
      try {
        await audio.play()
        setIsPlaying(true)
      } catch {
        setIsPlaying(false)
      } finally {
        setIsLoading(false)
      }
    } else {
      audio.pause()
      setIsPlaying(false)
    }
  }, [src])

  const seek = useCallback((next: number) => {
    const audio = internalRef.current
    if (!audio || !Number.isFinite(audio.duration)) return
    const clamped = Math.max(0, Math.min(audio.duration, next))
    audio.currentTime = clamped
    setCurrentTime(clamped)
  }, [])

  const setVolume = useCallback((next: number) => {
    const clamped = Math.max(0, Math.min(1, next))
    setVolumeState(clamped)
    if (internalRef.current) {
      internalRef.current.volume = clamped
    }
  }, [])

  const setPlaybackRate = useCallback((next: PlaybackRate) => {
    setPlaybackRateState(next)
    if (internalRef.current) {
      internalRef.current.playbackRate = next
    }
  }, [])

  useEffect(() => {
    const audio = internalRef.current
    if (!audio) return

    const handleLoadedMetadata = () => {
      const nextDuration = Number.isFinite(audio.duration) ? audio.duration : 0
      setDuration(nextDuration)
      setCurrentTime(audio.currentTime || 0)
      onLoadedMetadata?.(nextDuration)
    }

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime || 0)
      onTimeUpdate?.(audio.currentTime || 0)
    }

    const handleEnded = () => {
      setIsPlaying(false)
      onEnded?.()
    }

    const handlePlay = () => setIsPlaying(true)
    const handlePause = () => setIsPlaying(false)
    const handleWaiting = () => setIsLoading(true)
    const handleCanPlay = () => setIsLoading(false)

    audio.addEventListener('loadedmetadata', handleLoadedMetadata)
    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('ended', handleEnded)
    audio.addEventListener('play', handlePlay)
    audio.addEventListener('pause', handlePause)
    audio.addEventListener('waiting', handleWaiting)
    audio.addEventListener('canplay', handleCanPlay)

    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('ended', handleEnded)
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('waiting', handleWaiting)
      audio.removeEventListener('canplay', handleCanPlay)
    }
  }, [onEnded, onLoadedMetadata, onTimeUpdate, src])

  useEffect(() => {
    setIsPlaying(false)
    setIsLoading(false)
    setCurrentTime(0)
    setDuration(0)
  }, [src])

  useEffect(() => {
    const audio = internalRef.current
    if (!audio) return
    audio.volume = volume
    audio.playbackRate = playbackRate
  }, [playbackRate, volume, src])

  return {
    setAudioElementRef,
    getAudio,
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
    canSeek: Boolean(src) && duration > 0 && !isLoading,
  }
}
