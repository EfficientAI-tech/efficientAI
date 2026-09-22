import { useMemo, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { summarizeFlowchartError } from '../../../lib/apiErrors'

type FlowchartErrorPanelProps = {
  error: unknown
  title?: string
  className?: string
  /** Compact banner for toolbars; full panel for empty diagram areas. */
  variant?: 'inline' | 'panel'
}

export default function FlowchartErrorPanel({
  error,
  title = 'Could not generate flowchart',
  className = '',
  variant = 'panel',
}: FlowchartErrorPanelProps) {
  const { summary, details } = useMemo(() => summarizeFlowchartError(error), [error])
  const [showDetails, setShowDetails] = useState(false)

  if (!summary) return null

  if (variant === 'inline') {
    return (
      <div
        className={`rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 ${className}`}
        role="alert"
      >
        <p className="font-medium text-red-900">{title}</p>
        <p className="mt-0.5 break-words">{summary}</p>
        {details ? (
          <>
            <button
              type="button"
              className="mt-1 text-red-700 underline hover:text-red-900"
              onClick={() => setShowDetails((open) => !open)}
            >
              {showDetails ? 'Hide details' : 'Show details'}
            </button>
            {showDetails ? (
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded border border-red-100 bg-white/70 p-2 text-[10px] text-red-900/90">
                {details}
              </pre>
            ) : null}
          </>
        ) : null}
      </div>
    )
  }

  return (
    <div
      className={`flex h-full min-h-[200px] items-center justify-center p-6 ${className}`}
      role="alert"
    >
      <div className="w-full max-w-lg rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-red-900">{title}</p>
            <p className="mt-1 text-sm text-red-800 break-words">{summary}</p>
            {details ? (
              <>
                <button
                  type="button"
                  className="mt-2 text-xs font-medium text-red-700 underline hover:text-red-900"
                  onClick={() => setShowDetails((open) => !open)}
                >
                  {showDetails ? 'Hide technical details' : 'Show technical details'}
                </button>
                {showDetails ? (
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-red-100 bg-white/80 p-3 text-[11px] leading-relaxed text-red-900/90">
                    {details}
                  </pre>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
