export type ResultStatusDisplayOptions = {
  /** LLM-to-LLM text chat simulation (not a live phone/WebRTC call). */
  chatSimulation?: boolean
}

function humanizeStatus(status: string): string {
  return status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function statusLabel(status: string, options?: ResultStatusDisplayOptions): string {
  const chat = options?.chatSimulation
  switch (status) {
    case 'completed':
      return 'Completed'
    case 'failed':
      return 'Failed'
    case 'queued':
      return chat ? 'Queued' : 'Queued'
    case 'call_in_progress':
      return chat ? 'Chat in progress' : 'Live call'
    case 'call_initiating':
      return chat ? 'Simulating chat' : 'Initiating call'
    case 'call_connecting':
      return chat ? 'Connecting' : 'Connecting call'
    case 'call_ended':
      return chat ? 'Chat ended' : 'Call ended'
    case 'transcribing':
      return chat ? 'Simulating chat' : 'Transcribing'
    case 'evaluating':
      return chat ? 'Scoring chat' : 'Evaluating'
    case 'fetching_details':
      return chat ? 'Finalizing' : 'Fetching details'
    default:
      return humanizeStatus(status)
  }
}

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

export function getStatusConfig(
  status: string,
  options?: ResultStatusDisplayOptions,
): {
  dot: string
  bg: string
  text: string
  border: string
  label: string
  animate?: boolean
} {
  const chat = options?.chatSimulation
  const label = statusLabel(status, options)
  const inProgress =
    status === 'call_initiating' ||
    status === 'call_connecting' ||
    status === 'call_ended' ||
    status === 'transcribing' ||
    status === 'evaluating' ||
    status === 'fetching_details'

  switch (status) {
    case 'completed':
      return {
        dot: 'bg-emerald-500',
        bg: 'bg-emerald-50',
        text: 'text-emerald-700',
        border: 'border-emerald-200',
        label,
      }
    case 'failed':
      return {
        dot: 'bg-rose-500',
        bg: 'bg-rose-50',
        text: 'text-rose-700',
        border: 'border-rose-200',
        label,
      }
    case 'queued':
      return {
        dot: 'bg-slate-400',
        bg: 'bg-slate-50',
        text: 'text-slate-600',
        border: 'border-slate-200',
        label,
      }
    case 'call_in_progress':
      return {
        dot: chat ? 'bg-violet-500' : 'bg-blue-500',
        bg: chat ? 'bg-violet-50' : 'bg-blue-50',
        text: chat ? 'text-violet-700' : 'text-blue-700',
        border: chat ? 'border-violet-200' : 'border-blue-200',
        label,
        animate: true,
      }
    default:
      if (inProgress) {
        return {
          dot: chat ? 'bg-violet-500' : 'bg-blue-500',
          bg: chat ? 'bg-violet-50' : 'bg-blue-50',
          text: chat ? 'text-violet-700' : 'text-blue-700',
          border: chat ? 'border-violet-200' : 'border-blue-200',
          label,
          animate: true,
        }
      }
      return {
        dot: 'bg-gray-400',
        bg: 'bg-gray-50',
        text: 'text-gray-600',
        border: 'border-gray-200',
        label,
      }
  }
}
