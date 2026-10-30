import { useMemo, useState } from 'react'
import { AlertTriangle, Check, Eye, RotateCcw, Wrench } from 'lucide-react'
import Button from '../../../components/Button'
import type { Issue, IssueCategory, IssueSeverity, ReliabilityRow, Session } from '../../../lib/sandbox'
import {
  ISSUE_CATEGORY_LABELS,
  SEVERITY_LABELS,
  SOURCE_LABELS,
  openIssueCounts,
} from '../../../lib/sandbox'
import { IssueBadge, RoleBadge } from './badges'

export function IssueSummaryBar({
  issues,
  onReview,
}: {
  issues: Issue[]
  onReview?: () => void
}) {
  const counts = openIssueCounts(issues)
  const parts: string[] = []
  const byCat = new Map<IssueCategory, number>()
  for (const issue of issues.filter((i) => i.status === 'open')) {
    byCat.set(issue.category, (byCat.get(issue.category) ?? 0) + 1)
  }
  for (const [cat, n] of byCat) {
    parts.push(`${n} ${ISSUE_CATEGORY_LABELS[cat].toLowerCase()}${n === 1 ? '' : 's'}`)
  }
  const total = counts.error + counts.warning + counts.info
  if (total === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">
      <AlertTriangle className="h-4 w-4" aria-hidden />
      <span>
        {total} problem{total === 1 ? '' : 's'} found in this session
        {parts.length ? `: ${parts.join(', ')}` : ''}.
      </span>
      {onReview && (
        <Button size="sm" variant="outline" onClick={onReview}>
          Review issues
        </Button>
      )}
    </div>
  )
}

export function SessionIssueBanner({
  issues,
  onReview,
}: {
  issues: Issue[]
  onReview: () => void
}) {
  const [hidden, setHidden] = useState(false)
  const counts = openIssueCounts(issues)
  if (hidden || counts.error === 0) return null
  return (
    <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
      <p>
        {counts.error} problem{counts.error === 1 ? '' : 's'} found in this session. Review issues.
      </p>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={onReview}>
          Review issues
        </Button>
        <button type="button" className="text-xs text-rose-700 underline" onClick={() => setHidden(true)}>
          Dismiss banner
        </button>
      </div>
    </div>
  )
}

export function IssueCard({
  issue,
  onViewConversation,
  onViewTrace,
  onFixConfig,
  onDismiss,
  onRestore,
  sessionOnlyNote,
}: {
  issue: Issue
  onViewConversation?: () => void
  onViewTrace?: () => void
  onFixConfig?: () => void
  onDismiss?: () => void
  onRestore?: () => void
  sessionOnlyNote?: boolean
}) {
  return (
    <article className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <IssueBadge severity={issue.severity} label={SEVERITY_LABELS[issue.severity]} />
        <h3 className="text-sm font-semibold text-gray-900">{issue.title}</h3>
        <RoleBadge role={issue.agent} />
        {issue.turnIdx != null && <span className="text-xs text-gray-500">Turn {issue.turnIdx}</span>}
        <span className="text-xs text-gray-500">{SOURCE_LABELS[issue.source]}</span>
        <span className="text-xs text-gray-500">{ISSUE_CATEGORY_LABELS[issue.category]}</span>
      </div>
      <p className="mt-2 text-sm text-gray-800">{issue.whatHappened}</p>
      <p className="mt-1 text-sm text-gray-600">
        <span className="font-medium">What to check: </span>
        {issue.whatToCheck}
      </p>
      {issue.status === 'dismissed' && (
        <p className="mt-2 text-xs text-gray-500">
          {issue.rememberedFromSessionId
            ? `Dismissed in an earlier session${issue.dismissedAt ? ` (${new Date(issue.dismissedAt).toLocaleString()})` : ''}`
            : 'Dismissed in this session'}
          {issue.dismissReason ? ` — ${issue.dismissReason}` : ''}
        </p>
      )}
      {sessionOnlyNote && issue.status === 'open' && (
        <p className="mt-2 text-xs text-amber-800">
          This dismissal applies to this chat only until you save the agent.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {onViewConversation && (
          <Button size="sm" variant="ghost" leftIcon={<Eye className="h-3.5 w-3.5" />} onClick={onViewConversation}>
            View in conversation
          </Button>
        )}
        {onViewTrace && (
          <Button size="sm" variant="ghost" onClick={onViewTrace}>
            View trace
          </Button>
        )}
        {onFixConfig && (
          <Button size="sm" variant="outline" leftIcon={<Wrench className="h-3.5 w-3.5" />} onClick={onFixConfig}>
            Fix in config
          </Button>
        )}
        {issue.status === 'open' && onDismiss && (
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            Dismiss
          </Button>
        )}
        {issue.status === 'dismissed' && onRestore && (
          <Button size="sm" variant="ghost" leftIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={onRestore}>
            Restore
          </Button>
        )}
      </div>
    </article>
  )
}

export function ReliabilityTables({
  rows,
  onFilter,
}: {
  rows: ReliabilityRow[]
  onFilter?: (name: string) => void
}) {
  const groups: ReliabilityRow['kind'][] = ['tool', 'skill', 'api']
  const titles = { tool: 'Tools', skill: 'Skills', api: 'External APIs' }
  return (
    <div className="mt-6 grid gap-4 lg:grid-cols-3">
      {groups.map((kind) => {
        const list = rows.filter((r) => r.kind === kind)
        return (
          <section key={kind} className="rounded-lg border border-gray-200">
            <h4 className="border-b border-gray-100 px-3 py-2 text-xs font-semibold uppercase text-gray-500">
              {titles[kind]}
            </h4>
            {list.length === 0 ? (
              <p className="px-3 py-4 text-xs text-gray-500">No {titles[kind].toLowerCase()} in this session.</p>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="text-gray-500">
                  <tr>
                    <th className="px-3 py-1 font-medium">Name</th>
                    <th className="px-1 py-1 font-medium">Calls</th>
                    <th className="px-1 py-1 font-medium">Fail</th>
                    <th className="px-1 py-1 font-medium">ms</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((row) => (
                    <tr
                      key={row.name}
                      className={row.failures ? 'bg-rose-50' : ''}
                    >
                      <td className="px-3 py-1.5">
                        <button
                          type="button"
                          className="text-left font-medium text-gray-900 underline-offset-2 hover:underline"
                          onClick={() => onFilter?.(row.name)}
                        >
                          {row.name}
                        </button>
                        {row.topError && <p className="text-[10px] text-rose-700">{row.topError}</p>}
                      </td>
                      <td className="px-1 py-1.5">{row.calls}</td>
                      <td className="px-1 py-1.5">{row.failures}</td>
                      <td className="px-1 py-1.5">{row.avgLatencyMs ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )
      })}
    </div>
  )
}

export function IssuesTab({
  session,
  showDismissed,
  onShowDismissed,
  onViewConversation,
  onViewTrace,
  onFixConfig,
  onDismiss,
  onRestore,
}: {
  session: Session
  showDismissed: boolean
  onShowDismissed: (v: boolean) => void
  onViewConversation: (issue: Issue) => void
  onViewTrace: (issue: Issue) => void
  onFixConfig: (issue: Issue) => void
  onDismiss: (issue: Issue) => void
  onRestore: (issue: Issue) => void
}) {
  const [severity, setSeverity] = useState<'all' | IssueSeverity>('all')
  const [category, setCategory] = useState<'all' | IssueCategory>('all')
  const [agent, setAgent] = useState<'all' | 'A' | 'B'>('all')
  const [search, setSearch] = useState('')
  const [groupBy, setGroupBy] = useState<'category' | 'agent' | 'turn'>('category')
  const [nameFilter, setNameFilter] = useState('')

  const filtered = useMemo(() => {
    return session.issues.filter((issue) => {
      if (!showDismissed && issue.status === 'dismissed') return false
      if (severity !== 'all' && issue.severity !== severity) return false
      if (category !== 'all' && issue.category !== category) return false
      if (agent !== 'all' && issue.agent !== agent) return false
      if (nameFilter && !(issue.title + issue.whatHappened + (issue.configRef?.itemId ?? '')).toLowerCase().includes(nameFilter.toLowerCase())) {
        return false
      }
      if (search) {
        const blob = `${issue.title} ${issue.whatHappened} ${issue.whatToCheck}`.toLowerCase()
        if (!blob.includes(search.toLowerCase())) return false
      }
      return true
    })
  }, [session.issues, showDismissed, severity, category, agent, search, nameFilter])

  const grouped = useMemo(() => {
    const map = new Map<string, Issue[]>()
    for (const issue of filtered) {
      const key =
        groupBy === 'category'
          ? ISSUE_CATEGORY_LABELS[issue.category]
          : groupBy === 'agent'
            ? issue.agent === 'A'
              ? 'Main agent'
              : 'Test agent'
            : `Turn ${issue.turnIdx ?? '—'}`
      map.set(key, [...(map.get(key) ?? []), issue])
    }
    return [...map.entries()]
  }, [filtered, groupBy])

  const counts = openIssueCounts(session.issues)
  const totalOpen = counts.error + counts.warning + counts.info
  const sessionOnly = !session.agentA.platformAgentId
  const { tool, skill, api } = session.eventsChecked

  if (session.issues.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-600">
        <Check className="mx-auto mb-2 h-6 w-6 text-emerald-600" />
        No problems detected. {tool} tool calls, {skill} skill uses, {api} API calls checked.
      </div>
    )
  }

  return (
    <div>
      <IssueSummaryBar issues={session.issues} />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <select value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)} className="rounded border px-2 py-1">
          <option value="all">All severities</option>
          <option value="error">Error</option>
          <option value="warning">Warning</option>
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value as typeof category)} className="rounded border px-2 py-1">
          <option value="all">All categories</option>
          {Object.entries(ISSUE_CATEGORY_LABELS).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <select value={agent} onChange={(e) => setAgent(e.target.value as typeof agent)} className="rounded border px-2 py-1">
          <option value="all">Both agents</option>
          <option value="A">Main agent</option>
          <option value="B">Test agent</option>
        </select>
        <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as typeof groupBy)} className="rounded border px-2 py-1">
          <option value="category">Group by category</option>
          <option value="agent">Group by agent</option>
          <option value="turn">Group by turn</option>
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search issues"
          className="rounded border px-2 py-1"
        />
        <label className="ml-auto flex items-center gap-1 text-gray-600">
          <input type="checkbox" checked={showDismissed} onChange={(e) => onShowDismissed(e.target.checked)} />
          Show dismissed
        </label>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        {totalOpen} open · {session.issues.filter((i) => i.status === 'dismissed').length} dismissed · {filtered.length} shown
      </p>
      <div className="mt-4 space-y-5">
        {grouped.map(([label, items]) => (
          <section key={label}>
            <h3 className="mb-2 text-xs font-semibold uppercase text-gray-500">{label}</h3>
            <div className="space-y-2">
              {items.map((issue) => (
                <IssueCard
                  key={issue.id}
                  issue={issue}
                  sessionOnlyNote={sessionOnly}
                  onViewConversation={() => onViewConversation(issue)}
                  onViewTrace={() => onViewTrace(issue)}
                  onFixConfig={() => onFixConfig(issue)}
                  onDismiss={issue.status === 'open' ? () => onDismiss(issue) : undefined}
                  onRestore={issue.status === 'dismissed' ? () => onRestore(issue) : undefined}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
      <ReliabilityTables rows={session.reliability} onFilter={setNameFilter} />
    </div>
  )
}
