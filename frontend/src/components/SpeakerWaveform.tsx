import { useEffect, useState } from 'react'
import { Clock } from 'lucide-react'

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
    audio.addEventListener('pause', handlePause)
    audio.addEventListener('timeupdate', handleTimeUpdate)

    return () => {
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
    }
  }, [audioRef])

  // Get unique speakers
  const speakers = Array.from(new Set(speakerSegments.map((s) => s.speaker))).sort()
  
  // Color palette for speakers
  type ColorScheme = {
    bg: string
    light: string
    text: string
    border: string
  }
  
  const speakerColors: Record<string, ColorScheme> = {}
  const colors: ColorScheme[] = [
    { bg: 'bg-blue-500', light: 'bg-blue-100', text: 'text-blue-700', border: 'border-blue-300' },
    { bg: 'bg-green-500', light: 'bg-green-100', text: 'text-green-700', border: 'border-green-300' },
    { bg: 'bg-amber-500', light: 'bg-amber-100', text: 'text-amber-700', border: 'border-amber-300' },
    { bg: 'bg-red-500', light: 'bg-red-100', text: 'text-red-700', border: 'border-red-300' },
    { bg: 'bg-purple-500', light: 'bg-purple-100', text: 'text-purple-700', border: 'border-purple-300' },
    { bg: 'bg-pink-500', light: 'bg-pink-100', text: 'text-pink-700', border: 'border-pink-300' },
  ]
  
  speakers.forEach((speaker, idx) => {
    speakerColors[speaker] = colors[idx % colors.length]
  })

  // Calculate time markers
  const getTimeMarkers = () => {
    if (audioDuration === 0) return []
    const interval = audioDuration <= 60 ? 10 : audioDuration <= 300 ? 30 : 60
    const markers: number[] = []
    for (let i = 0; i <= audioDuration; i += interval) {
      markers.push(i)
    }
    if (markers[markers.length - 1] !== audioDuration) {
      markers.push(audioDuration)
    }
    return markers
  }

  const timeMarkers = getTimeMarkers()

  const handleSegmentClick = (start: number) => {
    const audio = audioRef.current
    if (audio) {
      audio.currentTime = start
    }
  }

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const getPercentage = (time: number) => {
    if (audioDuration === 0) return 0
    return (time / audioDuration) * 100
  }

  if (audioDuration === 0 || speakerSegments.length === 0) {
    return null
  }

  return (
    <div className="mt-6">
      <div className="flex items-center gap-2 mb-4">
        <Clock className="h-5 w-5 text-gray-500" />
        <h3 className="text-lg font-semibold text-gray-900">Speaker Timeline</h3>
      </div>
      
      <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm relative">
        {/* Time markers */}
        <div className="relative mb-6" style={{ height: '40px' }}>
          <div className="absolute top-0 left-0 right-0 h-0.5 bg-gray-300"></div>
          {timeMarkers.map((time) => {
            const position = getPercentage(time)
            return (
              <div
                key={time}
                className="absolute transform -translate-x-1/2"
                style={{ left: `${position}%` }}
              >
                <div className="w-0.5 h-3 bg-gray-400"></div>
                <div className="mt-1 text-xs text-gray-600 whitespace-nowrap">
                  {formatTime(time)}
                </div>
              </div>
            )
          })}
          
          {/* Playhead indicator on timeline */}
          {audioDuration > 0 && (
            <div
              className="absolute z-20 transform -translate-x-1/2"
              style={{ left: `${getPercentage(currentTime)}%`, top: '-2px' }}
            >
              <div className="w-0.5 h-5 bg-red-500"></div>
              <div className="absolute -top-2 -left-2 w-4 h-4 bg-red-500 rounded-full border-2 border-white shadow-md"></div>
            </div>
          )}
        </div>

        {/* Speaker segments */}
        <div className="relative space-y-4">
          {speakers.map((speaker) => {
            const speakerSegs = speakerSegments
              .filter((s) => s.speaker === speaker)
              .sort((a, b) => a.start - b.start)
            const colorScheme = speakerColors[speaker] || colors[0]

            return (
              <div key={speaker} className="relative">
                <div className="flex items-center gap-4">
                  {/* Speaker label */}
                  <div className="w-24 flex-shrink-0">
                    <div
                      className={`inline-flex items-center px-3 py-1.5 rounded-md font-semibold text-sm ${colorScheme.light} ${colorScheme.text} ${colorScheme.border} border`}
                    >
                      {speaker}
                    </div>
                  </div>

                  {/* Timeline track - using consistent width calculation */}
                  <div className="flex-1 relative h-16 bg-gray-50 rounded-lg border border-gray-200 overflow-hidden" style={{ minWidth: 0 }}>
                    {/* Time markers on track for alignment verification */}
                    {timeMarkers.map((time) => {
                      const position = getPercentage(time)
                      return (
                        <div
                          key={time}
                          className="absolute top-0 bottom-0 w-px bg-gray-300/50 pointer-events-none"
                          style={{ left: `${position}%` }}
                        />
                      )
                    })}
                    
                    {/* Playhead indicator on speaker track */}
                    {audioDuration > 0 && (
                      <div
                        className="absolute z-10 w-0.5 bg-red-500 h-full transition-all duration-100 pointer-events-none"
                        style={{ left: `${getPercentage(currentTime)}%` }}
                      >
                        <div className="absolute -top-1 -left-1.5 w-3 h-3 bg-red-500 rounded-full border border-white shadow-sm"></div>
                      </div>
                    )}
                    
                    {speakerSegs.map((segment, idx) => {
                      const left = getPercentage(segment.start)
                      const width = getPercentage(segment.end - segment.start)
                      const duration = segment.end - segment.start

                      return (
                        <div
                          key={idx}
                          onClick={() => handleSegmentClick(segment.start)}
                          className={`absolute top-0 h-full ${colorScheme.bg} cursor-pointer hover:opacity-90 transition-opacity rounded-sm border-r border-l border-white/20 flex items-center justify-center group`}
                          style={{
                            left: `${left}%`,
                            width: `${width}%`,
                            minWidth: '40px',
                          }}
                          title={`${formatTime(segment.start)} - ${formatTime(segment.end)}`}
                        >
                          {/* Timestamp labels - always show start time */}
                          <div className="absolute left-1 top-1 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded font-mono opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-20">
                            {formatTime(segment.start)}
                          </div>
                          
                          {/* End time label for larger segments */}
                          {width > 12 && (
                            <div className="absolute right-1 top-1 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded font-mono opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-20">
                              {formatTime(segment.end)}
                            </div>
                          )}
                          
                          {/* Duration badge for larger segments */}
                          {width > 15 && (
                            <div className="absolute bottom-1 right-1 bg-black/40 text-white text-[10px] px-1.5 py-0.5 rounded font-mono">
                              {duration.toFixed(1)}s
                            </div>
                          )}
                          
                          {/* Always visible start time indicator */}
                          <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-white/80"></div>
                          <div className="absolute right-0 top-0 bottom-0 w-0.5 bg-white/80"></div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Current time display */}
        <div className="mt-6 pt-4 border-t border-gray-200">
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-gray-500">Current position:</span>
              <span className="font-mono font-semibold text-gray-900">
                {formatTime(currentTime)}
              </span>
              <span className="text-gray-400">/</span>
              <span className="font-mono text-gray-600">{formatTime(audioDuration)}</span>
            </div>
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${isPlaying ? 'bg-green-500 animate-pulse' : 'bg-gray-400'}`}
              ></div>
              <span className="text-gray-500 text-xs">
                {isPlaying ? 'Playing' : 'Paused'}
              </span>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="mt-4 pt-4 border-t border-gray-200">
          <p className="text-xs text-gray-500">
            Click on any segment to jump to that timestamp. Hover over segments to see detailed timestamps.
          </p>
        </div>
      </div>
    </div>
  )
}
