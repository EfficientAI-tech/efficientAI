import { Search } from 'lucide-react'
import { formatDuration, sessionKindLabel, type SessionKind, type SessionListItem, type SessionStatus } from '../../../lib/sandbox'
import { IssueCountChips, SandboxStatusBadge, SessionTypeBadge } from './badges'

export function SandboxSessionTable({
  items,
  search,
  onSearch,
  typeFilter,
  onTypeFilter,
  statusFilter,
  onStatusFilter,
  hasIssuesOnly,
  onHasIssuesOnly,
  onOpen,
}: {
  items: SessionListItem[]
  search: string
  onSearch: (v: string) => void
  typeFilter: 'all' | SessionKind
  onTypeFilter: (v: 'all' | SessionKind) => void
  statusFilter: string
  onStatusFilter: (v: string) => void
  hasIssuesOnly: boolean
  onHasIssuesOnly: (v: boolean) => void
  onOpen: (id: string) => void
}) {
  return (
    <div>
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1">
          {(['all', 'simulation', 'manual'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onTypeFilter(value)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${
                typeFilter === value ? 'border-gray-300 bg-gray-200 text-gray-800' : 'border-transparent text-gray-600'
              }`}
            >
              {value === 'all' ? 'All types' : sessionKindLabel(value)}
            </button>
          ))}
          {(['all', 'running', 'completed', 'failed'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onStatusFilter(value)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${
                statusFilter === value ? 'border-gray-300 bg-gray-200 text-gray-800' : 'border-transparent text-gray-600'
              }`}
            >
              {value === 'all' ? 'All statuses' : value}
            </button>
          ))}
          <label className="ml-2 flex items-center gap-1 text-xs text-gray-600">
            <input type="checkbox" checked={hasIssuesOnly} onChange={(e) => onHasIssuesOnly(e.target.checked)} />
            Has issues
          </label>
        </div>
        <div className="relative w-full sm:w-auto">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            placeholder="Search session ID…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-1.5 pl-9 pr-3 text-sm sm:w-56"
          />
        </div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-3 py-2">Session</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Agents</th>
              <th className="px-3 py-2">Environment</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Issues</th>
              <th className="px-3 py-2">Accuracy</th>
              <th className="px-3 py-2">Experience</th>
              <th className="px-3 py-2">Duration</th>
              <th className="px-3 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="cursor-pointer border-t border-gray-100 hover:bg-gray-50"
                onClick={() => onOpen(item.id)}
              >
                <td className="px-3 py-2 font-mono text-xs">{item.id}</td>
                <td className="px-3 py-2">
                  <SessionTypeBadge kind={item.kind} />
                </td>
                <td className="px-3 py-2">
                  <p>
                    {item.agentAName} <span className="text-xs text-gray-500">{item.agentAModel}</span>
                  </p>
                  {item.agentBName && (
                    <p className="text-xs text-gray-500">
                      {item.agentBName} · {item.agentBModel}
                    </p>
                  )}
                </td>
                <td className="px-3 py-2">{item.environmentName}</td>
                <td className="px-3 py-2">
                  <SandboxStatusBadge status={item.status as SessionStatus} />
                </td>
                <td className="px-3 py-2">
                  <IssueCountChips error={item.openErrorCount} warning={item.openWarningCount} />
                </td>
                <td className="px-3 py-2">{item.accuracy == null ? '—' : Math.round(item.accuracy * 100)}</td>
                <td className="px-3 py-2">{item.experience == null ? '—' : Math.round(item.experience * 100)}</td>
                <td className="px-3 py-2">{formatDuration(item.durationSeconds)}</td>
                <td className="px-3 py-2 text-xs text-gray-500">{new Date(item.createdAt).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
