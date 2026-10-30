import { useMemo, useState } from 'react'
import {
  AGENT_TABLE_COLUMNS,
  type AgentTableColumn,
  useDashboardLayout,
} from './dashboardLayout'
import { AGENT_COLORS } from './dashboardSection'
import { agentTableRows } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { formatMoney } from './mockUsage'

export default function AgentsTableWidget() {
  const nav = useDashboardNav()
  const columns = useDashboardLayout((s) => s.tableColumns)
  const setTableColumns = useDashboardLayout((s) => s.setTableColumns)
  const [sort, setSort] = useState<{ id: AgentTableColumn; dir: 'asc' | 'desc' }>({ id: 'agent', dir: 'asc' })
  const rows = useMemo(() => {
    const list = agentTableRows(nav.calls)
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      const left = sort.id === 'agent' ? a.agentName : sort.id === 'cost' ? a.costUsd : a[sort.id]
      const right = sort.id === 'agent' ? b.agentName : sort.id === 'cost' ? b.costUsd : b[sort.id]
      if (typeof left === 'string' && typeof right === 'string') return left.localeCompare(right) * dir
      return ((left as number) - (right as number)) * dir
    })
  }, [nav.calls, sort])

  const toggleColumn = (id: AgentTableColumn) => {
    if (id === 'agent') return
    if (columns.includes(id)) setTableColumns(columns.filter((item) => item !== id))
    else setTableColumns([...columns, id])
  }

  return (
    <section className="flex h-full min-h-[360px] flex-1 flex-col overflow-hidden rounded-xl border border-indigo-100 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-indigo-50 bg-gradient-to-r from-indigo-50 via-sky-50 to-amber-50 px-5 py-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-gray-400">Table</p>
          <h3 className="mt-1 text-[15px] font-semibold text-gray-900">Agents</h3>
        </div>
        <div className="flex flex-wrap gap-1">
          {AGENT_TABLE_COLUMNS.filter((column) => column.id !== 'agent').map((column) => (
            <button
              key={column.id}
              type="button"
              onClick={() => toggleColumn(column.id)}
              className={`rounded-full px-2 py-0.5 text-[10px] ${
                columns.includes(column.id) ? 'bg-indigo-600 text-white' : 'bg-white/80 text-indigo-700'
              }`}
            >
              {column.label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-indigo-50/70 backdrop-blur">
            <tr className="text-left text-[11px] uppercase tracking-wide text-indigo-400">
              {AGENT_TABLE_COLUMNS.filter((column) => columns.includes(column.id)).map((column) => (
                <th key={column.id} className="px-5 py-3 font-medium">
                  <button
                    type="button"
                    onClick={() =>
                      setSort((current) => ({
                        id: column.id,
                        dir: current.id === column.id && current.dir === 'asc' ? 'desc' : 'asc',
                      }))
                    }
                  >
                    {column.label}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.agentId} className="border-t border-indigo-50 hover:bg-indigo-50/50">
                {columns.includes('agent') && (
                  <td className="px-5 py-3">
                    <button type="button" className="inline-flex items-center gap-2 font-medium text-gray-900 hover:underline" onClick={() => nav.openAgent(row.agentId)}>
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: AGENT_COLORS[row.agentId] ?? '#94a3b8' }} />
                      {row.agentName}
                    </button>
                  </td>
                )}
                {columns.includes('metrics') && <td className="px-5 py-3 tabular-nums text-gray-700">{row.metrics}</td>}
                {columns.includes('scenarios') && <td className="px-5 py-3 tabular-nums text-gray-700">{row.scenarios}</td>}
                {columns.includes('calls') && <td className="px-5 py-3 tabular-nums text-gray-700">{row.calls}</td>}
                {columns.includes('cost') && <td className="px-5 py-3 tabular-nums text-gray-700">{formatMoney(row.costUsd, nav.currency)}</td>}
                {columns.includes('tools') && <td className="px-5 py-3 tabular-nums text-gray-700">{row.tools}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
