import { AlertTriangle, MessageSquareOff, Mic } from 'lucide-react'

export function TalkOverBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
      <Mic className="h-3 w-3" />
      Talk-over
    </span>
  )
}

export function InterruptedBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-800">
      <MessageSquareOff className="h-3 w-3" />
      Interrupted
    </span>
  )
}

export function IncompleteTurnBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-gray-50 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
      <AlertTriangle className="h-3 w-3" />
      Incomplete
    </span>
  )
}

export function TurnSignalBadges({
  talkOver,
  interrupted,
  incomplete,
}: {
  talkOver?: boolean
  interrupted?: boolean
  incomplete?: boolean
}) {
  if (!talkOver && !interrupted && !incomplete) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {talkOver && <TalkOverBadge />}
      {interrupted && <InterruptedBadge />}
      {incomplete && <IncompleteTurnBadge />}
    </span>
  )
}
