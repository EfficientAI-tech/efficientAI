import { useMemo, useState } from 'react'
import { Bot, Link2Off, Search } from 'lucide-react'

export type ScenariosNavAgentId = string

interface AgentNavItem {
  id: string
  name: string
}

interface ScenariosAgentSidebarProps {
  agents: AgentNavItem[]
  selectedAgentId: ScenariosNavAgentId
  scenarioCountByAgent: Map<string, number>
  unlinkedCount: number
  onSelectAgent: (agentId: ScenariosNavAgentId) => void
}

export default function ScenariosAgentSidebar({
  agents,
  selectedAgentId,
  scenarioCountByAgent,
  unlinkedCount,
  onSelectAgent,
}: ScenariosAgentSidebarProps) {
  const [search, setSearch] = useState('')

  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return agents
    return agents.filter((agent) => agent.name.toLowerCase().includes(q))
  }, [agents, search])

  const showUnlinked =
    unlinkedCount > 0 ||
    search.trim().length === 0 ||
    'unlinked'.includes(search.trim().toLowerCase())

  return (
    <aside className="w-full lg:w-72 shrink-0 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col max-h-[70vh] lg:max-h-[calc(100vh-11rem)]">
      <div className="px-3 py-3 border-b border-gray-100 bg-gray-50 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-gray-900">Agents</h2>
          <span className="text-xs text-gray-500">{agents.length} total</span>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agents…"
            className="w-full rounded-lg border border-gray-200 py-1.5 pl-8 pr-2 text-xs focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto p-2" aria-label="Agents with scenarios">
        {showUnlinked ? (
          <button
            type="button"
            onClick={() => onSelectAgent('unlinked')}
            className={`mb-1 w-full text-left rounded-lg px-3 py-2.5 transition-colors ${
              selectedAgentId === 'unlinked'
                ? 'bg-primary-50 ring-1 ring-primary-200'
                : 'hover:bg-gray-50'
            }`}
          >
            <div className="flex items-center gap-2">
              <Link2Off className="h-4 w-4 text-gray-400 shrink-0" />
              <span className="text-sm font-medium text-gray-900">Unlinked</span>
              <span className="ml-auto text-xs text-gray-500 tabular-nums">{unlinkedCount}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5 pl-6">Scenarios without a linked agent</p>
          </button>
        ) : null}

        {filteredAgents.length === 0 && search.trim() ? (
          <p className="px-2 py-4 text-sm text-gray-500">No agents match your search.</p>
        ) : (
          filteredAgents.map((agent) => {
            const count = scenarioCountByAgent.get(agent.id) ?? 0
            const isActive = selectedAgentId === agent.id
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => onSelectAgent(agent.id)}
                className={`mb-1 w-full text-left rounded-lg px-3 py-2.5 transition-colors ${
                  isActive ? 'bg-primary-50 ring-1 ring-primary-200' : 'hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Bot className="h-4 w-4 text-primary-600 shrink-0" />
                  <span className="text-sm font-medium text-gray-900 truncate">{agent.name}</span>
                  <span className="ml-auto text-xs text-gray-500 tabular-nums shrink-0">{count}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 pl-6">
                  {count === 1 ? '1 scenario' : `${count} scenarios`}
                </p>
              </button>
            )
          })
        )}

        {agents.length === 0 && unlinkedCount === 0 ? (
          <p className="px-2 py-4 text-sm text-gray-500">
            No linked agents yet. Link a scenario to an agent to see it here.
          </p>
        ) : null}
      </nav>
    </aside>
  )
}
