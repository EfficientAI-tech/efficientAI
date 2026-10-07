import { useState, useRef, useEffect } from 'react'
import { Info } from 'lucide-react'

type AlertingPageShellProps = {
  title: string
  actions?: React.ReactNode
}

const HELP_LINES = [
  'Alerts run automatically about every 5 minutes.',
  'When a rule is exceeded, we notify your team and list it in Alert history.',
  'With “Notify once”, you get one notification per issue until you resolve it.',
  'Acknowledge to show you’re on it; resolve when it’s fixed. Issues can also close on their own when readings stay healthy.',
  'Lifecycle sync (ack/resolve across PagerDuty, Slack, email) is off unless an org admin enables it under IAM → Organization.',
]

export function AlertingHelpButton() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
        aria-label="How alerting works"
        title="How alerting works"
      >
        <Info className="w-5 h-5" />
      </button>
      {open && (
        <div
          className="absolute left-0 top-full z-20 mt-1 w-64 rounded-lg border border-gray-200 bg-white p-3 shadow-lg text-xs text-gray-600 space-y-1.5"
          role="dialog"
        >
          {HELP_LINES.map(line => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function AlertingPageShell({ title, actions }: AlertingPageShellProps) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-1">
        <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
        <AlertingHelpButton />
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
