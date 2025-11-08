import { useEffect, useRef, useState } from 'react'

interface SpeakerSegment {
  speaker: string
  text: string
  start: number
  end: number
}

interface SpeakerWaveformProps {
  audioDuration: number
  speakerSegments: SpeakerSegment[]
  audioRef: React.RefObject<HTMLAudioElement>
}

export default function SpeakerWaveform({
  audioDuration,
  speakerSegments,
  audioRef,
}: SpeakerWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const handlePlay = () => setIsPlaying(true)
    const handlePause = () => setIsPlaying(false)
    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      setIsPlaying(!audio.paused)
    }

    audio.addEventListener('play', handlePlay)
    audio.addEventListener('pause', handlePlay)
    audio.addEventListener('timeupdate', handleTimeUpdate)

    return () => {
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
    }
  }, [audioRef])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !audioDuration || speakerSegments.length === 0) return

    // Get device pixel ratio for crisp rendering
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    const displayWidth = Math.max(rect.width || 800, 800) // Minimum width for readability
    const padding = 20
    const waveformHeight = 60
    const timelineHeight = 30
    const totalHeight = waveformHeight * 2 + timelineHeight + padding * 3

    // Set display size (CSS pixels)
    canvas.style.width = displayWidth + 'px'
    canvas.style.height = totalHeight + 'px'

    // Set actual size in memory (scaled for device pixel ratio)
    canvas.width = displayWidth * dpr
    canvas.height = totalHeight * dpr

    const ctx = canvas.getContext('2d', { alpha: false }) // Disable alpha for better performance
    if (!ctx) return

    // Scale the context to match device pixel ratio
    ctx.scale(dpr, dpr)

    const width = displayWidth

    // Clear canvas
    ctx.clearRect(0, 0, width, totalHeight)

    // Get unique speakers
    const speakers = Array.from(new Set(speakerSegments.map((s) => s.speaker))).sort()
    const speakerColors: Record<string, string> = {}
    const colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899']
    speakers.forEach((speaker, idx) => {
      speakerColors[speaker] = colors[idx % colors.length]
    })

    // Draw timeline
    const timelineY = padding
    ctx.strokeStyle = '#E5E7EB'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(padding, timelineY)
    ctx.lineTo(width - padding, timelineY)
    ctx.stroke()

    // Draw time markers
    const numMarkers = Math.min(15, Math.floor(audioDuration / 5)) // More markers for longer audio
    ctx.fillStyle = '#6B7280'
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    for (let i = 0; i <= numMarkers; i++) {
      const time = (audioDuration / numMarkers) * i
      const x = padding + ((width - padding * 2) / numMarkers) * i
      ctx.beginPath()
      ctx.moveTo(x, timelineY - 5)
      ctx.lineTo(x, timelineY + 5)
      ctx.stroke()
      ctx.fillText(formatTime(time), x, timelineY - 18)
    }

    // Draw speaker waveforms
    speakers.forEach((speaker, speakerIdx) => {
      const y = padding + timelineHeight + padding + speakerIdx * (waveformHeight + padding)
      const speakerSegs = speakerSegments.filter((s) => s.speaker === speaker)

      // Draw background
      ctx.fillStyle = '#F9FAFB'
      ctx.fillRect(padding, y, width - padding * 2, waveformHeight)

      // Draw segments for this speaker
      speakerSegs.forEach((segment) => {
        const startX = padding + ((segment.start / audioDuration) * (width - padding * 2))
        const endX = padding + ((segment.end / audioDuration) * (width - padding * 2))
        const segmentWidth = endX - startX

        // Draw waveform bar (simplified - just a rectangle with height variation)
        ctx.fillStyle = speakerColors[speaker] || '#6B7280'
        const barHeight = waveformHeight * 0.7
        const barY = y + (waveformHeight - barHeight) / 2
        ctx.fillRect(startX, barY, segmentWidth, barHeight)

        // Draw speaker label
        if (segmentWidth > 50) {
          ctx.fillStyle = '#FFFFFF'
          ctx.font = 'bold 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'top'
          ctx.fillText(speaker, startX + 4, y + 15)
        }
      })

      // Draw speaker label on the left
      ctx.fillStyle = '#374151'
      ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      ctx.fillText(speaker, 4, y + waveformHeight / 2)
    })

    // Draw current time indicator
    if (audioDuration > 0) {
      const currentX = padding + ((currentTime / audioDuration) * (width - padding * 2))
      ctx.strokeStyle = '#EF4444'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(currentX, padding)
      ctx.lineTo(currentX, totalHeight - padding)
      ctx.stroke()

      // Draw playhead circle
      ctx.fillStyle = '#EF4444'
      ctx.beginPath()
      ctx.arc(currentX, padding, 5, 0, Math.PI * 2)
      ctx.fill()
      
      // Add white border to playhead for visibility
      ctx.strokeStyle = '#FFFFFF'
      ctx.lineWidth = 1.5
      ctx.stroke()
    }
  }, [audioDuration, speakerSegments, currentTime, isPlaying])

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-gray-700 mb-2">Speaker Timeline</h3>
      <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 overflow-x-auto">
        <canvas
          ref={canvasRef}
          className="w-full"
          style={{ 
            height: 'auto',
            minHeight: '200px',
            imageRendering: 'crisp-edges',
            imageRendering: '-webkit-optimize-contrast'
          }}
        />
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Visual representation of speaker segments. Red line indicates current playback position.
      </p>
    </div>
  )
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

