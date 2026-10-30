import { useMemo, useState } from 'react'
import { Download, X } from 'lucide-react'
import Button from '../../../components/Button'
import type { ActivityEvent, EventType, Session, Span } from '../../../lib/sandbox'
import { EVENT_TYPE_LABELS, eventStatusLabel } from '../../../lib/sandbox'

function spanTone(span: Span) {
  if (span.status !== 'ok' || span.issueId) {
    return 'bg-rose-400'
  }
  return 'bg-indigo-400'
}

export function SpanDetailDrawer({
  span,
  event,
  onClose,
}: {
  span: Span | null
  event?: ActivityEvent
  onClose: () => void
}) {
  if (!span) return null
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-gray-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-900">{span.name}</h2>
        <button type="button" onClick={onClose} aria-label="Close span detail">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-3 overflow-y-auto p-4 text-sm">
        <p>Type: {EVENT_TYPE_LABELS[span.type]}</p>
        <p>Agent: {span.agent === 'A' ? 'Main' : 'Test'}</p>
        <p>Status: {eventStatusLabel(span.status)}</p>
        <p>Duration: {span.durationMs}ms</p>
        {span.issueId && <p className="text-rose-700">Related issue: {span.issueId}</p>}
        <pre className="max-h-80 overflow-auto rounded bg-gray-50 p-2 text-[11px]">
          {JSON.stringify(span.attributes ?? event ?? {}, null, 2)}
        </pre>
      </div>
    </div>
  )
}

function TimelineLane({
  spans,
  total,
  onSelect,
}: {
  spans: Span[]
  total: number
  onSelect: (span: Span) => void
}) {
  const width = Math.max(total, 1)
  return (
    <div className="relative h-16 rounded-lg bg-gray-50">
      {spans.map((span) => (
        <button
          key={span.id}
          type="button"
          title={span.name}
          onClick={() => onSelect(span)}
          className={`absolute top-3 h-8 rounded ${spanTone(span)} opacity-90 hover:opacity-100`}
          style={{
            left: `${(span.startMs / width) * 100}%`,
            width: `${Math.max(1.5, (span.durationMs / width) * 100)}%`,
          }}
        >
          <span className="sr-only">{span.name}</span>
        </button>
      ))}
    </div>
  )
}

export function DualTraceView({
  session,
  issuesOnly,
  onSelectSpan,
}: {
  session: Session
  issuesOnly: boolean
  onSelectSpan: (span: Span) => void
}) {
  const [merged, setMerged] = useState(false)
  const filter = (spans: Span[]) => (issuesOnly ? spans.filter((s) => s.status !== 'ok' || s.issueId) : spans)
  const a = filter(session.traces.A)
  const b = filter(session.traces.B ?? [])
  const total = Math.max(1, ...[...a, ...b].map((s) => s.startMs + s.durationMs))
  const all = [...a, ...b]

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-xs">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={merged} onChange={(e) => setMerged(e.target.checked)} />
          Merged timeline
        </label>
      </div>
      <div className="relative mb-2 h-2 overflow-hidden rounded bg-gray-100" aria-hidden>
        {all
          .filter((s) => s.status !== 'ok' || s.issueId)
          .map((s) => (
            <span
              key={s.id}
              className="absolute h-2 w-1 bg-rose-500"
              style={{ marginLeft: `${(s.startMs / total) * 100}%` }}
            />
          ))}
      </div>
      {merged || !session.traces.B ? (
        <TimelineLane spans={all} total={total} onSelect={onSelectSpan} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium text-gray-500">Agent A</p>
            <TimelineLane spans={a} total={total} onSelect={onSelectSpan} />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-gray-500">Agent B</p>
            <TimelineLane spans={b} total={total} onSelect={onSelectSpan} />
          </div>
        </div>
      )}
      {all.length === 0 && <p className="mt-4 text-sm text-gray-500">No spans to show.</p>}
    </div>
  )
}

function exportRows(rows: ActivityEvent[], asCsv: boolean) {
  const blob = asCsv
    ? new Blob(
        [
          ['ts', 'agent', 'type', 'name', 'status', 'durationMs'].join(',') +
            '\n' +
            rows
              .map((r) => [r.ts, r.agent, r.type, r.name, r.status, r.durationMs ?? ''].join(','))
              .join('\n'),
        ],
        { type: 'text/csv' },
      )
    : new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = asCsv ? 'sandbox-activity.csv' : 'sandbox-activity.json'
  a.click()
  URL.revokeObjectURL(url)
}

export function ActivityLogTable({
  session,
  issuesOnly,
  onSelectEvent,
}: {
  session: Session
  issuesOnly: boolean
  onSelectEvent: (event: ActivityEvent) => void
}) {
  const [agent, setAgent] = useState<'all' | 'A' | 'B'>('all')
  const [type, setType] = useState<'all' | EventType>('all')
  const [status, setStatus] = useState<'all' | 'ok' | 'error'>('all')
  const [search, setSearch] = useState('')

  const rows = useMemo(() => {
    return session.events.filter((event) => {
      if (issuesOnly && event.status === 'ok' && !session.issues.some((i) => i.eventIds.includes(event.id) && i.status === 'open')) {
        return false
      }
      if (agent !== 'all' && event.agent !== agent) return false
      if (type !== 'all' && event.type !== type) return false
      if (status === 'ok' && event.status !== 'ok') return false
      if (status === 'error' && event.status === 'ok') return false
      if (search && !`${event.name} ${event.type} ${event.error?.message ?? ''}`.toLowerCase().includes(search.toLowerCase())) {
        return false
      }
      return true
    })
  }, [session, issuesOnly, agent, type, status, search])

  const rowHeight = 36
  const height = Math.min(480, Math.max(rowHeight * 8, rows.length * rowHeight))
  const [scrollTop, setScrollTop] = useState(0)
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 4)
  const visible = rows.slice(start, start + Math.ceil(height / rowHeight) + 8)

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <select value={agent} onChange={(e) => setAgent(e.target.value as typeof agent)} className="rounded border px-2 py-1">
          <option value="all">All agents</option>
          <option value="A">Main</option>
          <option value="B">Test</option>
        </select>
        <select value={type} onChange={(e) => setType(e.target.value as typeof type)} className="rounded border px-2 py-1">
          <option value="all">All types</option>
          {Object.entries(EVENT_TYPE_LABELS).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className="rounded border px-2 py-1">
          <option value="all">All statuses</option>
          <option value="ok">OK</option>
          <option value="error">Error</option>
        </select>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search log" className="rounded border px-2 py-1" />
        <Button size="sm" variant="ghost" leftIcon={<Download className="h-3.5 w-3.5" />} onClick={() => exportRows(rows, false)}>
          JSON
        </Button>
        <Button size="sm" variant="ghost" onClick={() => exportRows(rows, true)}>
          CSV
        </Button>
      </div>
      <div
        className="overflow-auto rounded-lg border border-gray-200"
        style={{ height }}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
      >
        <div style={{ height: rows.length * rowHeight, position: 'relative' }}>
          {visible.map((event, i) => {
            const idx = start + i
            const hasIssue = session.issues.some((iss) => iss.eventIds.includes(event.id) && iss.status === 'open')
            return (
              <button
                key={event.id}
                type="button"
                onClick={() => onSelectEvent(event)}
                className={`absolute left-0 right-0 grid grid-cols-6 items-center px-3 text-left text-xs ${
                  hasIssue || event.status !== 'ok' ? 'bg-rose-50' : idx % 2 ? 'bg-gray-50' : 'bg-white'
                }`}
                style={{ top: idx * rowHeight, height: rowHeight }}
              >
                <span className="truncate text-gray-500">{new Date(event.ts).toLocaleTimeString()}</span>
                <span>{event.agent}</span>
                <span>{EVENT_TYPE_LABELS[event.type]}</span>
                <span className="truncate font-medium">{event.name}</span>
                <span>{eventStatusLabel(event.status)}</span>
                <span>{event.durationMs ?? '—'}{event.error ? ` · ${event.error.message}` : ''}</span>
              </button>
            )
          })}
          {rows.length === 0 && (
            <p className="p-6 text-center text-sm text-gray-500">No events match these filters.</p>
          )}
        </div>
      </div>
    </div>
  )
}

export function TracesTab({
  session,
  onJumpIssue,
}: {
  session: Session
  onJumpIssue?: (issueId: string) => void
}) {
  const [mode, setMode] = useState<'timeline' | 'log'>('timeline')
  const [issuesOnly, setIssuesOnly] = useState(false)
  const [span, setSpan] = useState<Span | null>(null)
  const event = span ? session.events.find((e) => e.id === span.eventId) : undefined

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-gray-200 p-0.5 text-xs">
          <button
            type="button"
            className={`rounded-md px-3 py-1 ${mode === 'timeline' ? 'bg-gray-900 text-white' : 'text-gray-600'}`}
            onClick={() => setMode('timeline')}
          >
            Timeline
          </button>
          <button
            type="button"
            className={`rounded-md px-3 py-1 ${mode === 'log' ? 'bg-gray-900 text-white' : 'text-gray-600'}`}
            onClick={() => setMode('log')}
          >
            Activity log
          </button>
        </div>
        <label className="flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" checked={issuesOnly} onChange={(e) => setIssuesOnly(e.target.checked)} />
          Issues only
        </label>
      </div>
      {mode === 'timeline' ? (
        <DualTraceView
          session={session}
          issuesOnly={issuesOnly}
          onSelectSpan={(next) => {
            setSpan(next)
            if (next.issueId) onJumpIssue?.(next.issueId)
          }}
        />
      ) : (
        <ActivityLogTable
          session={session}
          issuesOnly={issuesOnly}
          onSelectEvent={(event) => {
            const found =
              session.traces.A.find((s) => s.eventId === event.id) ||
              session.traces.B?.find((s) => s.eventId === event.id)
            setSpan(
              found ?? {
                id: event.id,
                name: event.name,
                type: event.type,
                agent: event.agent,
                startMs: 0,
                durationMs: event.durationMs ?? 0,
                status: event.status,
                eventId: event.id,
                attributes: { input: event.input, output: event.output, error: event.error },
              },
            )
          }}
        />
      )}
      <SpanDetailDrawer span={span} event={event} onClose={() => setSpan(null)} />
    </div>
  )
}
