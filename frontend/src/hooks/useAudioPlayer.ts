import { useState, useRef, useCallback } from 'react'

export function useAudioPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const play = useCallback((id: string, url: string) => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    
    if (playingId === id) {
      setPlayingId(null)
      return
    }
    
    setIsLoading(true)
    const audio = new Audio(url)
    
    audio.oncanplaythrough = () => {
      setIsLoading(false)
    }
    
    audio.onended = () => {
      setPlayingId(null)
      audioRef.current = null
    }
    
    audio.onerror = () => {
      setPlayingId(null)
      setIsLoading(false)
      audioRef.current = null
    }
    
    audio.play().catch(() => {
      setPlayingId(null)
      setIsLoading(false)
    })
    
    audioRef.current = audio
    setPlayingId(id)
  }, [playingId])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setPlayingId(null)
  }, [])

  const isPlaying = useCallback((id: string) => {
    return playingId === id
  }, [playingId])

  return { 
    playingId, 
    play, 
    stop, 
    isPlaying,
    isLoading 
  }
}
