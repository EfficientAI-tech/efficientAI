import { Clock, Loader2, CheckCircle2, XCircle } from 'lucide-react'

interface StatusBadgeProps {
  status: string
  size?: 'sm' | 'md'
}

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-700',
  queued: 'bg-gray-100 text-gray-700',
  generating: 'bg-yellow-100 text-yellow-800',
  evaluating: 'bg-blue-100 text-blue-800',
  processing: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-700',
  call_initiating: 'bg-yellow-100 text-yellow-800',
  call_connecting: 'bg-yellow-100 text-yellow-800',
  call_in_progress: 'bg-blue-100 text-blue-800',
  call_ended: 'bg-green-100 text-green-800',
  transcribing: 'bg-blue-100 text-blue-800',
}

export default function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const normalizedStatus = status.toLowerCase()
  const style = STATUS_STYLES[normalizedStatus] || STATUS_STYLES.pending
  
  const iconClass = size === 'sm' ? 'w-2.5 h-2.5' : 'w-3 h-3'
  const paddingClass = size === 'sm' ? 'px-2 py-0.5' : 'px-2.5 py-1'
  const textClass = size === 'sm' ? 'text-[10px]' : 'text-xs'
  
  const renderIcon = () => {
    if (['generating', 'evaluating', 'processing', 'call_initiating', 'call_connecting', 'call_in_progress', 'transcribing'].includes(normalizedStatus)) {
      return <Loader2 className={`${iconClass} animate-spin`} />
    }
    if (normalizedStatus === 'completed' || normalizedStatus === 'call_ended') {
      return <CheckCircle2 className={iconClass} />
    }
    if (normalizedStatus === 'failed') {
      return <XCircle className={iconClass} />
    }
    return <Clock className={iconClass} />
  }
  
  return (
    <span className={`inline-flex items-center gap-1 ${paddingClass} rounded-full ${textClass} font-medium ${style}`}>
      {renderIcon()}
      {status}
    </span>
  )
}
