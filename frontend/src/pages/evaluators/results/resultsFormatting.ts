export function formatDuration(seconds: number | null): string {
  if (!seconds) return '--'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function getStatusConfig(status: string): {
  dot: string
  bg: string
  text: string
  border: string
  label: string
  animate?: boolean
} {
  switch (status) {
    case 'completed':
      return {
        dot: 'bg-emerald-500',
        bg: 'bg-emerald-50',
        text: 'text-emerald-700',
        border: 'border-emerald-200',
        label: 'Completed',
      }
    case 'failed':
      return {
        dot: 'bg-rose-500',
        bg: 'bg-rose-50',
        text: 'text-rose-700',
        border: 'border-rose-200',
        label: 'Failed',
      }
    case 'queued':
      return {
        dot: 'bg-slate-400',
        bg: 'bg-slate-50',
        text: 'text-slate-600',
        border: 'border-slate-200',
        label: 'Queued',
      }
    case 'call_in_progress':
      return {
        dot: 'bg-blue-500',
        bg: 'bg-blue-50',
        text: 'text-blue-700',
        border: 'border-blue-200',
        label: 'Live call',
        animate: true,
      }
    case 'call_initiating':
    case 'call_connecting':
    case 'call_ended':
    case 'transcribing':
    case 'evaluating':
    case 'fetching_details':
      return {
        dot: 'bg-blue-500',
        bg: 'bg-blue-50',
        text: 'text-blue-700',
        border: 'border-blue-200',
        label: status.replace(/_/g, ' '),
        animate: true,
      }
    default:
      return {
        dot: 'bg-gray-400',
        bg: 'bg-gray-50',
        text: 'text-gray-600',
        border: 'border-gray-200',
        label: status,
      }
  }
}
