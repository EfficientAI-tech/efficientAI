import { useCallback, useRef, useState } from 'react'

const DEFAULT_PREVIEW_VOLUME = 0.7

export type AmbientPreviewSource = string | Blob

export function formatPlaybackTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function useAmbientPreview() {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const volumeRef = useRef(DEFAULT_PREVIEW_VOLUME)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const [volume, setVolumeState] = useState(DEFAULT_PREVIEW_VOLUME)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const resetPlaybackState = useCallback(() => {
    setCurrentTime(0)
    setDuration(0)
  }, [])

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.onloadedmetadata = null
      audioRef.current.ontimeupdate = null
      audioRef.current.onended = null
      audioRef.current.onerror = null
      audioRef.current = null
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
    resetPlaybackState()
  }, [resetPlaybackState])

  const stop = useCallback(() => {
    cleanup()
    setPlayingId(null)
    setLoadingId(null)
  }, [cleanup])

  const setVolume = useCallback((next: number) => {
    const clamped = Math.max(0, Math.min(1, next))
    volumeRef.current = clamped
    setVolumeState(clamped)
    if (audioRef.current) {
      audioRef.current.volume = clamped
    }
  }, [])

  const seek = useCallback((next: number) => {
    if (!audioRef.current || !Number.isFinite(audioRef.current.duration)) return
    const clamped = Math.max(0, Math.min(audioRef.current.duration, next))
    audioRef.current.currentTime = clamped
    setCurrentTime(clamped)
  }, [])

  const attachAudio = useCallback((audio: HTMLAudioElement) => {
    audio.loop = true
    audio.preload = 'metadata'
    audio.volume = volumeRef.current
    audio.onloadedmetadata = () => {
      setDuration(Number.isFinite(audio.duration) ? audio.duration : 0)
      setCurrentTime(audio.currentTime || 0)
    }
    audio.ontimeupdate = () => {
      setCurrentTime(audio.currentTime || 0)
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        setDuration(audio.duration)
      }
    }
    audio.onended = () => {
      stop()
    }
    audio.onerror = () => {
      setError('Could not play this audio file.')
      stop()
    }
  }, [stop])

  const togglePreview = useCallback(
    async (id: string, loadSource: () => Promise<AmbientPreviewSource>) => {
      if (playingId === id || loadingId === id) {
        stop()
        return
      }

      cleanup()
      setError(null)
      setLoadingId(id)

      try {
        const source = await loadSource()
        const url = typeof source === 'string' ? source : URL.createObjectURL(source)
        if (typeof source !== 'string') {
          objectUrlRef.current = url
        }

        const audio = new Audio(url)
        attachAudio(audio)

        await audio.play()
        audioRef.current = audio
        setPlayingId(id)
      } catch (err: any) {
        const detail = err?.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'Preview unavailable.')
        stop()
      } finally {
        setLoadingId(null)
      }
    },
    [attachAudio, cleanup, loadingId, playingId, stop],
  )

  return {
    playingId,
    loadingId,
    volume,
    currentTime,
    duration,
    error,
    togglePreview,
    setVolume,
    seek,
    stop,
    isPlaying: (id: string) => playingId === id,
    isLoading: (id: string) => loadingId === id,
    isActive: (id: string) => playingId === id || loadingId === id,
  }
}

export function defaultNameFromFilename(filename: string): string {
  const base = filename.replace(/\.[^.]+$/, '')
  const cleaned = base.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
  return cleaned || 'Ambient bed'
}

export function formatPreviewVolume(volume: number): string {
  return `${Math.round(volume * 100)}%`
}
