import { Activity } from 'lucide-react'

type PlaygroundTraceOpenButtonProps = {
  onOpen: () => void
  title?: string
}

export default function PlaygroundTraceOpenButton({
  onOpen,
  title = 'View call trace',
}: PlaygroundTraceOpenButtonProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
      title={title}
    >
      <Activity className="h-3.5 w-3.5" />
      Trace
    </button>
  )
}
