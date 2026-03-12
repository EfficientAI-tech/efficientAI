import { Clock, CheckCircle2, XCircle, Loader2 } from 'lucide-react'

interface StatusBadgeProps {
  status: string
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const s = status.toLowerCase()
  let bg = 'bg-gray-100 text-gray-700'
  let icon = <Clock className="w-3 h-3" />

  if (s === 'completed') {
    bg = 'bg-green-100 text-green-800'
    icon = <CheckCircle2 className="w-3 h-3" />
  } else if (s === 'failed') {
    bg = 'bg-red-100 text-red-700'
    icon = <XCircle className="w-3 h-3" />
  } else if (['generating', 'evaluating', 'processing', 'synthesizing'].includes(s)) {
    bg = 'bg-blue-100 text-blue-800'
    icon = <Loader2 className="w-3 h-3 animate-spin" />
  }

  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${bg}`}>
      {icon}
      {status}
    </span>
  )
}
