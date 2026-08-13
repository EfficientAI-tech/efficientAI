import { FileText } from 'lucide-react'
import TranscriptView from '../../callImports/components/TranscriptView'

type MetricsStudioTranscriptPanelProps = {
  transcript: string | null | undefined
  transcriptSource: 'production' | 'diarised' | string
}

function transcriptSourceLabel(source: string): string {
  return source === 'production' ? 'Production (CSV)' : 'Diarised'
}

export default function MetricsStudioTranscriptPanel({
  transcript,
  transcriptSource,
}: MetricsStudioTranscriptPanelProps) {
  if (!transcript?.trim()) return null

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-4 space-y-2">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-gray-500" />
        <h4 className="text-sm font-semibold text-gray-900">
          Evaluation transcript
        </h4>
        <span className="px-2 py-0.5 text-xs rounded-full bg-white border border-gray-200 text-gray-600">
          {transcriptSourceLabel(transcriptSource)}
        </span>
      </div>
      <div className="max-h-64 overflow-y-auto rounded-md border border-gray-100 bg-white p-3">
        <TranscriptView transcript={transcript} />
      </div>
    </div>
  )
}
