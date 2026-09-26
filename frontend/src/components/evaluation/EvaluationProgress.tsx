import { useEffect, useState } from 'react'
import { CheckCircle, Loader } from 'lucide-react'

export function isEvaluationRunning(status: string | null | undefined): boolean {
  return Boolean(status && ['queued', 'transcribing', 'evaluating'].includes(status))
}

export function EvaluationStepper({ status }: { status: string }) {
  const [dots, setDots] = useState('')

  useEffect(() => {
    const id = setInterval(() => setDots((prev) => (prev.length >= 3 ? '' : prev + '.')), 500)
    return () => clearInterval(id)
  }, [])

  const steps = [
    { key: 'queued', label: 'Queued', sublabel: 'Preparing worker' },
    { key: 'transcribing', label: 'Analyzing Audio', sublabel: 'Acoustic & voice quality' },
    { key: 'evaluating', label: 'Evaluating', sublabel: 'LLM conversation metrics' },
  ]

  const activeIdx = Math.max(0, steps.findIndex((s) => s.key === status))

  const statusMessages: Record<string, string> = {
    queued: 'Downloading audio & preparing evaluation',
    transcribing: 'Running acoustic analysis & voice quality metrics',
    evaluating: 'Evaluating conversation quality with LLM',
  }

  return (
    <div className="py-8 px-4">
      <div className="flex items-start justify-center max-w-md mx-auto">
        {steps.map((step, idx) => {
          const isActive = idx === activeIdx
          const isDone = idx < activeIdx

          return (
            <div key={step.key} className="flex items-start" style={{ minWidth: idx < steps.length - 1 ? undefined : 90 }}>
              <div className="flex flex-col items-center" style={{ minWidth: 90 }}>
                <div
                  className={[
                    'w-11 h-11 rounded-full flex items-center justify-center transition-all duration-500 relative',
                    isDone ? 'bg-emerald-500 text-white shadow-md' : '',
                    isActive ? 'bg-blue-600 text-white shadow-lg shadow-blue-200' : '',
                    !isDone && !isActive ? 'bg-gray-100 text-gray-400 border-2 border-gray-200' : '',
                  ].join(' ')}
                >
                  {isActive && (
                    <span className="absolute inset-0 rounded-full animate-ping bg-blue-400 opacity-30" />
                  )}
                  {isDone ? (
                    <CheckCircle className="w-5 h-5" />
                  ) : isActive ? (
                    <Loader className="w-5 h-5 animate-spin" />
                  ) : (
                    <span className="text-sm font-semibold">{idx + 1}</span>
                  )}
                </div>
                <p
                  className={`mt-2.5 text-xs font-semibold text-center leading-tight ${isActive ? 'text-blue-700' : isDone ? 'text-emerald-600' : 'text-gray-400'}`}
                >
                  {step.label}
                </p>
                <p
                  className={`text-[10px] text-center leading-tight mt-0.5 ${isActive ? 'text-blue-500' : isDone ? 'text-emerald-500' : 'text-gray-300'}`}
                >
                  {step.sublabel}
                </p>
              </div>
              {idx < steps.length - 1 && (
                <div className="flex-1 flex items-center pt-1" style={{ minWidth: 40 }}>
                  <div className="w-full relative h-1 rounded-full bg-gray-200 overflow-hidden" style={{ marginTop: 18 }}>
                    <div
                      className={`absolute inset-y-0 left-0 rounded-full transition-all duration-700 ${isDone ? 'w-full bg-emerald-400' : isActive ? 'bg-blue-400 animate-[indeterminate_1.5s_ease-in-out_infinite]' : 'w-0'}`}
                      style={isActive ? { width: '60%' } : undefined}
                    />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-6 text-center">
        <span className="inline-flex items-center gap-2 px-4 py-2 bg-blue-50 border border-blue-100 rounded-full text-sm text-blue-700">
          <Loader className="w-3.5 h-3.5 animate-spin" />
          {statusMessages[status] || 'Processing'}
          {dots}
        </span>
      </div>
    </div>
  )
}

export function EvaluationMetricsLoading({ status }: { status?: string }) {
  const stepStatus = isEvaluationRunning(status) ? status! : 'queued'
  return (
    <div className="space-y-4 py-4">
      <div className="flex flex-col items-center justify-center gap-2 text-sm text-gray-600">
        <Loader className="h-6 w-6 animate-spin text-primary-500" />
        Loading evaluation results…
      </div>
      {isEvaluationRunning(status) ? <EvaluationStepper status={stepStatus} /> : null}
    </div>
  )
}
