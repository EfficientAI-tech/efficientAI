import { useState } from 'react'
import type { DbDiff, Session } from '../../../lib/sandbox'

export function SeedDataViewer({
  data,
  collapsedByDefault = true,
}: {
  data: Record<string, unknown>
  collapsedByDefault?: boolean
}) {
  const [open, setOpen] = useState(!collapsedByDefault)
  return (
    <div className="rounded-lg border border-gray-200">
      <button
        type="button"
        className="w-full px-3 py-2 text-left text-xs font-medium text-gray-700"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? 'Hide' : 'Show'} seed data
      </button>
      {open && (
        <pre className="max-h-64 overflow-auto border-t border-gray-100 bg-gray-50 p-3 text-[11px] text-gray-700">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

export function DbDiffViewer({ diff }: { diff: DbDiff }) {
  const empty = !diff.added.length && !diff.changed.length && !diff.removed.length
  if (empty) {
    return <p className="text-sm text-gray-500">No database changes.</p>
  }
  return (
    <div className="space-y-2 text-xs">
      {diff.added.map((row, i) => (
        <pre key={`a-${i}`} className="rounded bg-emerald-50 p-2 text-emerald-800">
          + {JSON.stringify(row, null, 2)}
        </pre>
      ))}
      {diff.changed.map((row) => (
        <div key={row.path} className="rounded bg-amber-50 p-2 text-amber-900">
          <p className="font-medium">{row.path}</p>
          <p>before: {JSON.stringify(row.before)}</p>
          <p>after: {JSON.stringify(row.after)}</p>
        </div>
      ))}
      {diff.removed.map((row, i) => (
        <pre key={`r-${i}`} className="rounded bg-rose-50 p-2 text-rose-800">
          − {JSON.stringify(row, null, 2)}
        </pre>
      ))}
    </div>
  )
}

export function EnvironmentTab({ session, onJumpTurn }: { session: Session; onJumpTurn?: (idx: number) => void }) {
  const dbEvents = session.events.filter((e) => e.type === 'db' || (e.type === 'tool' && (e.name === 'get_entry' || e.name === 'record_entry')))
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section>
        <h3 className="text-sm font-semibold text-gray-900">Initial</h3>
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-gray-50 p-3 text-[11px] text-gray-700">
          {JSON.stringify(session.environment.seed, null, 2)}
        </pre>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-gray-900">Final</h3>
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-gray-50 p-3 text-[11px] text-gray-700">
          {JSON.stringify(session.environment.final ?? session.environment.current ?? session.environment.seed, null, 2)}
        </pre>
      </section>
      <section className="lg:col-span-2">
        <h3 className="text-sm font-semibold text-gray-900">Diff</h3>
        <div className="mt-2">
          {session.results?.outcome.dbDiff ? (
            <DbDiffViewer diff={session.results.outcome.dbDiff} />
          ) : (
            <p className="text-sm text-gray-500">No scored diff for this session.</p>
          )}
        </div>
      </section>
      <section className="lg:col-span-2">
        <h3 className="text-sm font-semibold text-gray-900">DB reads and writes</h3>
        {dbEvents.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No database activity.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-200 text-sm">
            {dbEvents.map((event) => (
              <li key={event.id} className="flex items-center justify-between px-3 py-2">
                <span>
                  {event.type} · {event.name} · {event.status}
                </span>
                {event.turnIdx != null && onJumpTurn && (
                  <button
                    type="button"
                    className="text-xs text-indigo-700 underline"
                    onClick={() => onJumpTurn(event.turnIdx!)}
                  >
                    Turn {event.turnIdx}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
