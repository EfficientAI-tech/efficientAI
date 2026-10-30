import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Database, Globe, Sparkles, Wrench } from 'lucide-react'
import type { ActivityEvent, Issue, Session, Turn } from '../../../lib/sandbox'
import { EVENT_TYPE_LABELS } from '../../../lib/sandbox'
import { IssueBadge, RoleBadge } from './badges'

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-48 overflow-auto rounded bg-gray-50 p-2 text-[11px] text-gray-700">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function EventCard({
  event,
  issue,
  onIssue,
}: {
  event: ActivityEvent
  issue?: Issue
  onIssue?: (id: string) => void
}) {
  const [open, setOpen] = useState(Boolean(issue && issue.status === 'open'))
  const failed = event.status !== 'ok'
  const border = failed
    ? issue?.severity === 'warning'
      ? 'border-amber-300 bg-amber-50/40'
      : 'border-rose-300 bg-rose-50/40'
    : 'border-gray-200 bg-white'
  const Icon =
    event.type === 'tool'
      ? Wrench
      : event.type === 'api'
        ? Globe
        : event.type === 'skill'
          ? Sparkles
          : event.type === 'rag'
            ? Sparkles
            : Database
  const writes = event.type === 'tool' && event.name === 'record_entry'

  return (
    <div className={`mt-2 rounded-lg border ${border}`}>
      <div className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs">
        <button type="button" onClick={() => setOpen((v) => !v)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <Icon className="h-3.5 w-3.5 text-gray-500" aria-hidden />
          <span className="font-medium text-gray-900">{event.name}</span>
          <span className="text-gray-500">{EVENT_TYPE_LABELS[event.type]}</span>
          {writes && (
            <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-800">
              writes to DB
            </span>
          )}
          {event.durationMs != null && <span className="text-gray-400">{event.durationMs}ms</span>}
          {event.api && (
            <span className="text-gray-500">
              {event.api.method} {event.api.host}
              {event.api.statusCode != null ? ` ${event.api.statusCode}` : ''}
              {event.api.retries ? ` · ${event.api.retries} retries` : ''}
            </span>
          )}
        </button>
        {issue && (
          <IssueBadge
            severity={issue.severity}
            label={issue.title}
            onClick={() => onIssue?.(issue.id)}
          />
        )}
      </div>
      {open && (
        <div className="border-t border-gray-100 px-3 py-2 text-xs text-gray-700">
          {event.error && <p className="font-medium text-rose-700">{event.error.message}</p>}
          {event.input !== undefined && (
            <>
              <p className="mt-1 font-medium text-gray-500">Arguments</p>
              <JsonBlock value={event.input} />
            </>
          )}
          {event.output !== undefined && (
            <>
              <p className="mt-1 font-medium text-gray-500">Result</p>
              <JsonBlock value={event.output} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function ToolCallCard(props: {
  event: ActivityEvent
  issue?: Issue
  onIssue?: (id: string) => void
}) {
  return <EventCard {...props} />
}

export function SkillCard(props: {
  event: ActivityEvent
  issue?: Issue
  onIssue?: (id: string) => void
}) {
  return <EventCard {...props} />
}

export function ExternalApiCard(props: {
  event: ActivityEvent
  issue?: Issue
  onIssue?: (id: string) => void
}) {
  return <EventCard {...props} />
}

export function RetrievalCard(props: {
  event: ActivityEvent
  issue?: Issue
  onIssue?: (id: string) => void
}) {
  return <EventCard {...props} />
}

function TurnRow({
  turn,
  session,
  highlight,
  onIssue,
  actions,
}: {
  turn: Turn
  session: Session
  highlight?: boolean
  onIssue?: (id: string) => void
  actions?: React.ReactNode
}) {
  if (turn.divider) {
    return (
      <div className="my-3 flex items-center gap-3 text-[11px] uppercase tracking-wide text-gray-500">
        <div className="h-px flex-1 bg-gray-200" />
        {turn.dividerSummary || turn.divider.replace('_', ' ')}
        <div className="h-px flex-1 bg-gray-200" />
      </div>
    )
  }

  const events = (turn.eventIds ?? [])
    .map((id) => session.events.find((ev) => ev.id === id))
    .filter((event): event is ActivityEvent => event != null && event.type !== 'message')
  const issuesForTurn = session.issues.filter((i) => i.turnIdx === turn.idx)
  const hasOpenIssue = issuesForTurn.some((i) => i.status === 'open')
  const alignRight = turn.speaker === 'human' || turn.speaker === 'B'

  return (
    <div
      id={`sandbox-turn-${turn.idx}`}
      className={`flex gap-3 ${alignRight ? 'flex-row-reverse' : ''} ${highlight ? 'rounded-lg ring-2 ring-amber-300' : ''}`}
    >
      {hasOpenIssue && (
        <div
          className="mt-2 w-1 shrink-0 rounded-full bg-rose-400"
          aria-label="This turn has issues"
        />
      )}
      <div className={`max-w-[85%] ${alignRight ? 'text-right' : ''}`}>
        <div className="mb-1 flex items-center gap-2 text-[11px] text-gray-500">
          <RoleBadge role={turn.speaker} />
          <span>Turn {turn.idx}</span>
          {turn.flaggedByUser && <span className="text-amber-700">Flagged</span>}
        </div>
        <div
          className={`rounded-2xl px-3 py-2 text-sm ${
            turn.speaker === 'A'
              ? 'bg-violet-50 text-violet-950'
              : turn.speaker === 'B'
                ? 'bg-teal-50 text-teal-950'
                : 'bg-gray-100 text-gray-900'
          }`}
        >
          {turn.text}
        </div>
        {events.map((event) => (
          <EventCard
            key={event.id}
            event={event}
            issue={session.issues.find((i) => i.eventIds.includes(event.id) && i.status !== 'dismissed') || session.issues.find((i) => i.eventIds.includes(event.id))}
            onIssue={onIssue}
          />
        ))}
        {actions && <div className="mt-1">{actions}</div>}
      </div>
    </div>
  )
}

export function ConversationView({
  session,
  highlightTurn,
  onIssue,
  renderActions,
  streaming,
  showHiddenInstruction,
}: {
  session: Session
  highlightTurn?: number
  onIssue?: (id: string) => void
  renderActions?: (turn: Turn) => React.ReactNode
  streaming?: boolean
  showHiddenInstruction?: boolean
}) {
  const turns = useMemo(
    () => session.turns.filter((t) => !session.activeBranchId || !t.branchId || t.branchId === session.activeBranchId || t.divider),
    [session],
  )

  return (
    <div className="space-y-4">
      {showHiddenInstruction && session.scenario && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-3 py-2 text-xs text-gray-600">
          <span className="font-medium text-gray-700">Hidden from Agent A: </span>
          {session.scenario}
        </div>
      )}
      <div className="max-h-[640px] space-y-4 overflow-y-auto pr-1">
        {turns.length === 0 && (
          <p className="py-8 text-center text-sm text-gray-500">No turns yet.</p>
        )}
        {turns.map((turn) => (
          <TurnRow
            key={`${turn.idx}-${turn.divider ?? 'msg'}`}
            turn={turn}
            session={session}
            highlight={highlightTurn === turn.idx}
            onIssue={onIssue}
            actions={renderActions?.(turn)}
          />
        ))}
        {streaming && (
          <p className="text-sm text-gray-500" aria-live="polite">
            Agent is typing…
          </p>
        )}
      </div>
    </div>
  )
}
