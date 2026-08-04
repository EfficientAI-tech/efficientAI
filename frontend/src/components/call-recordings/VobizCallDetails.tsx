interface VobizCallDetailsProps {
  callData: Record<string, any>
}

function formatDuration(callData: Record<string, any>): string | null {
  if (typeof callData.duration_seconds === 'number' && callData.duration_seconds > 0) {
    const total = Math.floor(callData.duration_seconds)
    const mins = Math.floor(total / 60)
    const secs = total % 60
    return `${mins}m ${secs}s`
  }
  const started = callData.startedAt || callData.started_at
  const ended = callData.endedAt || callData.ended_at
  if (started && ended) {
    const diffSec = Math.floor((new Date(ended).getTime() - new Date(started).getTime()) / 1000)
    if (diffSec > 0) {
      const mins = Math.floor(diffSec / 60)
      const secs = diffSec % 60
      return `${mins}m ${secs}s`
    }
  }
  return null
}

export default function VobizCallDetails({ callData }: VobizCallDetailsProps) {
  const fromNumber = callData.from_phone_number || callData.from_number || callData.From
  const toNumber = callData.to_phone_number || callData.to_number || callData.To
  const direction = callData.direction
  const duration = formatDuration(callData)
  const recordingUrl = callData.recording_url

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
        {direction && (
          <div>
            <dt className="text-gray-500">Direction</dt>
            <dd className="font-medium text-gray-900 capitalize">{direction}</dd>
          </div>
        )}
        {duration && (
          <div>
            <dt className="text-gray-500">Duration</dt>
            <dd className="font-medium text-gray-900 tabular-nums">{duration}</dd>
          </div>
        )}
        {fromNumber && (
          <div>
            <dt className="text-gray-500">From</dt>
            <dd className="font-mono text-gray-900">{fromNumber}</dd>
          </div>
        )}
        {toNumber && (
          <div>
            <dt className="text-gray-500">To</dt>
            <dd className="font-mono text-gray-900">{toNumber}</dd>
          </div>
        )}
        {callData.call_short_id && (
          <div>
            <dt className="text-gray-500">Call ID</dt>
            <dd className="font-mono text-gray-900">{callData.call_short_id}</dd>
          </div>
        )}
      </dl>
      {recordingUrl && (
        <div>
          <p className="text-sm text-gray-500 mb-1">Recording</p>
          <a
            href={recordingUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-primary-600 hover:text-primary-800"
          >
            Open provider recording
          </a>
        </div>
      )}
    </div>
  )
}
