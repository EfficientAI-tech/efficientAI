import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import AudioCard from './AudioCard'
import { TTSSample } from '../types'

interface SampleGroupProps {
  sampleIndex: number
  text: string
  samples: TTSSample[]
  providerA: string
  providerB?: string
  playingId: string | null
  onPlay: (id: string, url: string) => void
  numRuns: number
  hzMapA?: Record<string, number>
  hzMapB?: Record<string, number>
}

export default function SampleGroup({
  sampleIndex,
  text,
  samples,
  providerA,
  providerB,
  playingId,
  onPlay,
  numRuns,
  hzMapA,
  hzMapB,
}: SampleGroupProps) {
  const [expanded, setExpanded] = useState(false)
  const hasSideField = samples.some((s) => s.side)
  const aSamples = samples.filter((s) => (hasSideField ? s.side === 'A' : s.provider === providerA))
  const bSamples = providerB
    ? samples.filter((s) => (hasSideField ? s.side === 'B' : s.provider === providerB))
    : []

  return (
    <div className="bg-gray-50 rounded-lg border border-gray-200 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-700">Sample {sampleIndex + 1}</span>
          <span className="text-xs text-gray-400 truncate max-w-md">{text}</span>
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-gray-200 p-4 space-y-3">
          <p className="text-sm text-gray-700 italic mb-3">&ldquo;{text}&rdquo;</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <h5 className="text-xs font-semibold text-blue-600 mb-2">Provider A</h5>
              {aSamples.map((sample) => (
                <AudioCard
                  key={sample.id}
                  sample={sample}
                  colorClass="blue"
                  playingId={playingId}
                  onPlay={onPlay}
                  showRun={numRuns > 1}
                  sampleRateHz={hzMapA?.[sample.voice_id]}
                />
              ))}
            </div>
            {bSamples.length > 0 && (
              <div>
                <h5 className="text-xs font-semibold text-purple-600 mb-2">Provider B</h5>
                {bSamples.map((sample) => (
                  <AudioCard
                    key={sample.id}
                    sample={sample}
                    colorClass="purple"
                    playingId={playingId}
                    onPlay={onPlay}
                    showRun={numRuns > 1}
                    sampleRateHz={hzMapB?.[sample.voice_id]}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
