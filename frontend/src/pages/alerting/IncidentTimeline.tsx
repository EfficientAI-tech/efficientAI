import { TimelineStep } from './incidentActivityUtils'
import { formatRelativeTime } from './alertUiUtils'

const TONE_DOT: Record<TimelineStep['tone'], string> = {
  red: 'bg-red-500',
  amber: 'bg-amber-500',
  blue: 'bg-blue-500',
  emerald: 'bg-emerald-500',
  gray: 'bg-gray-400',
}

function formatAt(at: string) {
  try {
    return `${formatRelativeTime(at)} · ${new Date(at).toLocaleString()}`
  } catch {
    return at
  }
}

export default function IncidentTimeline({ steps }: { steps: TimelineStep[] }) {
  if (steps.length === 0) {
    return <p className="text-sm text-gray-500">No timeline events yet.</p>
  }

  return (
    <ol className="space-y-0">
      {steps.map((step, idx) => {
        const isLast = idx === steps.length - 1
        return (
          <li key={step.key} className={`relative pl-6 pb-6 ${isLast ? '' : 'border-l-2 border-gray-200'}`}>
            <span
              className={`absolute left-0 top-1.5 -translate-x-1/2 h-2.5 w-2.5 rounded-full ring-4 ring-white ${TONE_DOT[step.tone]}`}
            />
            <h4 className="text-sm font-semibold text-gray-900">{step.title}</h4>
            {step.at && <p className="text-xs text-gray-500 mt-0.5">{formatAt(step.at)}</p>}
            {step.meta && <p className="text-xs text-gray-600 mt-1">{step.meta}</p>}
            {step.body && (
              <p className="text-sm text-gray-700 mt-2 rounded-lg border border-gray-200 bg-white px-3 py-2">
                {step.body}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
