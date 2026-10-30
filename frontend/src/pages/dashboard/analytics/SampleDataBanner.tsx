import { FlaskConical } from 'lucide-react'
import { useMockDataStore } from './mockMode'

export default function SampleDataBanner() {
  const enabled = useMockDataStore((s) => s.enabled)
  const setEnabled = useMockDataStore((s) => s.setEnabled)

  if (!enabled) {
    return (
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={() => setEnabled(true)}
          className="text-xs font-medium text-gray-500 underline hover:text-gray-800"
        >
          Show sample data
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5">
      <div className="flex items-center gap-2 text-sm text-amber-900">
        <FlaskConical className="h-4 w-4 text-amber-600" />
        <span>
          <span className="font-semibold">Sample data.</span> These agents, scores, and
          suggestions are generated so you can see how the dashboard reads. Nothing here is from
          your workspace.
        </span>
      </div>
      <button
        type="button"
        onClick={() => setEnabled(false)}
        className="rounded-lg border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100"
      >
        Use my real data
      </button>
    </div>
  )
}
