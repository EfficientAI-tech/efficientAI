import { Play, Pause, XCircle, Loader2 } from 'lucide-react'
import { TTSSample } from '../types'

function HzBadge({ hz }: { hz?: number | null }) {
  if (!hz) return null
  const label = hz >= 1000 ? `${(hz / 1000).toFixed(1).replace(/\.0$/, '')} kHz` : `${hz} Hz`
  return (
    <span className="text-[9px] font-medium bg-gray-100 text-gray-500 px-1 py-0.5 rounded">
      {label}
    </span>
  )
}

interface AudioCardProps {
  sample: TTSSample
  colorClass: 'blue' | 'purple'
  playingId: string | null
  onPlay: (id: string, url: string) => void
  showRun?: boolean
  sampleRateHz?: number
}

export default function AudioCard({
  sample,
  colorClass,
  playingId,
  onPlay,
  showRun = false,
  sampleRateHz,
}: AudioCardProps) {
  const isPlaying = playingId === sample.id
  const borderC = colorClass === 'blue' ? 'border-blue-100' : 'border-purple-100'
  const bgC = colorClass === 'blue' ? 'bg-blue-50' : 'bg-purple-50'
  const textC = colorClass === 'blue' ? 'text-blue-600' : 'text-purple-600'

  return (
    <div className={`p-3 ${bgC} rounded-lg border ${borderC} mb-2`}>
      <div className="flex items-center gap-2">
        {sample.audio_url ? (
          <button
            onClick={() => onPlay(sample.id, sample.audio_url!)}
            className={`w-8 h-8 rounded-full ${
              colorClass === 'blue'
                ? 'bg-blue-600 hover:bg-blue-700'
                : 'bg-purple-600 hover:bg-purple-700'
            } text-white flex items-center justify-center transition-colors flex-shrink-0`}
          >
            {isPlaying ? (
              <Pause className="w-3.5 h-3.5" />
            ) : (
              <Play className="w-3.5 h-3.5 ml-0.5" />
            )}
          </button>
        ) : (
          <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0">
            {sample.status === 'failed' ? (
              <XCircle className="w-3.5 h-3.5 text-red-400" />
            ) : (
              <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />
            )}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className={`text-sm font-medium ${textC}`}>
              {sample.voice_name || sample.voice_id}
            </p>
            <HzBadge hz={sampleRateHz} />
            {showRun && (
              <span className="text-[10px] bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded">
                Run {(sample.run_index ?? 0) + 1}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
            {sample.ttfb_ms != null && (
              <span title="Time-to-first-byte">TTFB: {Math.round(sample.ttfb_ms)}ms</span>
            )}
            {sample.latency_ms != null && (
              <span title="Total synthesis latency">Total: {Math.round(sample.latency_ms)}ms</span>
            )}
            {sample.duration_seconds != null && (
              <span>Duration: {sample.duration_seconds.toFixed(1)}s</span>
            )}
          </div>
        </div>
      </div>
      {/* Metrics row */}
      {sample.evaluation_metrics && (
        <div className="flex flex-wrap gap-2 mt-2">
          {sample.evaluation_metrics['MOS Score'] != null && (
            <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">
              MOS: {sample.evaluation_metrics['MOS Score']}
            </span>
          )}
          {sample.evaluation_metrics['Prosody Score'] != null && (
            <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">
              Prosody: {sample.evaluation_metrics['Prosody Score']}
            </span>
          )}
          {sample.evaluation_metrics['Valence'] != null && (
            <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">
              Valence: {sample.evaluation_metrics['Valence']}
            </span>
          )}
          {sample.evaluation_metrics['Arousal'] != null && (
            <span className="text-[10px] bg-white px-1.5 py-0.5 rounded border text-gray-600">
              Arousal: {sample.evaluation_metrics['Arousal']}
            </span>
          )}
          {sample.evaluation_metrics['WER'] != null && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
                (sample.evaluation_metrics['WER'] as number) < 0.1
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : (sample.evaluation_metrics['WER'] as number) < 0.3
                  ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
                  : 'bg-red-50 border-red-200 text-red-700'
              }`}
            >
              WER: {((sample.evaluation_metrics['WER'] as number) * 100).toFixed(1)}%
            </span>
          )}
          {sample.evaluation_metrics['CER'] != null && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
                (sample.evaluation_metrics['CER'] as number) < 0.05
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : (sample.evaluation_metrics['CER'] as number) < 0.15
                  ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
                  : 'bg-red-50 border-red-200 text-red-700'
              }`}
            >
              CER: {((sample.evaluation_metrics['CER'] as number) * 100).toFixed(1)}%
            </span>
          )}
        </div>
      )}
    </div>
  )
}

