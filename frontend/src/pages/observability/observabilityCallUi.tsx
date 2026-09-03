import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../config/providers'
import { IntegrationPlatform } from '../../types/api'

export function EventBadge({ event }: { event?: string }) {
  if (!event) return <span className="text-gray-400">&mdash;</span>

  const variants: Record<
    string,
    { label: string; bg: string; text: string; border: string; dot: string; pulse?: boolean }
  > = {
    outbound_initiated: {
      label: 'Ringing',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      dot: 'bg-amber-500',
      pulse: true,
    },
    ringing: {
      label: 'Ringing',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      dot: 'bg-amber-500',
      pulse: true,
    },
    call_in_progress: {
      label: 'In Progress',
      bg: 'bg-sky-50',
      text: 'text-sky-700',
      border: 'border-sky-200',
      dot: 'bg-sky-500',
      pulse: true,
    },
    call_started: {
      label: 'Call Started',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
      dot: 'bg-blue-500',
    },
    call_ended: {
      label: 'Call Ended',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      dot: 'bg-emerald-500',
    },
    failed: {
      label: 'Failed',
      bg: 'bg-rose-50',
      text: 'text-rose-700',
      border: 'border-rose-200',
      dot: 'bg-rose-500',
    },
    call_analyzed: {
      label: 'Call Analyzed',
      bg: 'bg-purple-50',
      text: 'text-purple-700',
      border: 'border-purple-200',
      dot: 'bg-purple-500',
    },
  }

  const variant = variants[event.toLowerCase()] || {
    label: event,
    bg: 'bg-gray-50',
    text: 'text-gray-600',
    border: 'border-gray-200',
    dot: 'bg-gray-400',
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${variant.bg} ${variant.text} ${variant.border}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${variant.dot} ${variant.pulse ? 'animate-pulse' : ''}`} />
      {variant.label}
    </span>
  )
}

export function EndReasonBadge({ reason }: { reason: string }) {
  const colors: Record<string, string> = {
    'customer-hungup': 'bg-amber-50 text-amber-700 border-amber-200',
    'assistant-ended-call': 'bg-blue-50 text-blue-700 border-blue-200',
    voicemail: 'bg-purple-50 text-purple-700 border-purple-200',
    error: 'bg-rose-50 text-rose-700 border-rose-200',
  }

  const colorClass = colors[reason.toLowerCase()] || 'bg-gray-50 text-gray-700 border-gray-200'
  const label = reason.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())

  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${colorClass}`}>
      {label}
    </span>
  )
}

export function PlatformBadge({ platform }: { platform?: string }) {
  if (!platform) return <span className="text-gray-400">N/A</span>
  const normalized = platform.toLowerCase() as IntegrationPlatform
  const label = getIntegrationPlatformLabel(normalized)
  const logo = getIntegrationPlatformLogo(normalized)

  return (
    <span className="inline-flex items-center gap-2 text-sm text-gray-700">
      {logo && <img src={logo} alt={label} className="h-5 w-5 object-contain" />}
      <span>{label}</span>
    </span>
  )
}
