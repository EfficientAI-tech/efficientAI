import { PhoneCall } from 'lucide-react'

export default function LiveSourceNotice({
  liveCalls,
  compact,
}: {
  liveCalls: number | null
  compact?: boolean
}) {
  if (compact) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-teal-200 bg-teal-50/70 px-3 py-2 text-xs text-teal-900">
        <PhoneCall className="h-3.5 w-3.5 shrink-0" />
        Showing sample live calls
        {liveCalls != null ? ` (${liveCalls.toLocaleString()} in the hub)` : ''}. Charts overlay teal live vs indigo simulations.
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-teal-200 bg-teal-50/70 px-5 py-6">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-teal-100 p-2">
          <PhoneCall className="h-5 w-5 text-teal-700" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-gray-900">Live scoring is not enabled yet</h2>
          <p className="mt-1 text-sm text-gray-600 max-w-2xl">
            This workspace has{' '}
            <span className="font-medium text-gray-900">
              {liveCalls == null ? 'no counted' : liveCalls.toLocaleString()} live calls
            </span>{' '}
            in the calls hub. Those calls are not scored against your metrics today. When live
            auto-scoring is turned on, this agent’s real-call scores will appear on the same
            charts as simulations, in teal.
          </p>
        </div>
      </div>
    </div>
  )
}
