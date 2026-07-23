import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { TestAgent, Integration, IntegrationPlatform } from '../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../../config/providers'

export function agentRouteId(agent: TestAgent): string {
  return agent.agent_id || agent.id
}

export function agentMatchesRoute(agent: TestAgent, routeId: string): boolean {
  return agent.id === routeId || agent.agent_id === routeId
}

interface AgentsListSidebarProps {
  agents: TestAgent[]
  integrations: Integration[]
  selectedRouteId: string | undefined
  selectedAgents: Set<string>
  isLoading: boolean
  onSelectAgent: (agent: TestAgent) => void
  onSelectAgentCheckbox: (agentId: string, checked: boolean) => void
  onSelectAll: () => void
}

export default function AgentsListSidebar({
  agents,
  integrations,
  selectedRouteId,
  selectedAgents,
  isLoading,
  onSelectAgent,
  onSelectAgentCheckbox,
  onSelectAll,
}: AgentsListSidebarProps) {
  const [search, setSearch] = useState('')

  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return agents
    return agents.filter((agent) => {
      const id = agent.agent_id?.toLowerCase() || ''
      const name = agent.name.toLowerCase()
      const internal = agent.id.toLowerCase()
      return id.includes(q) || name.includes(q) || internal.includes(q)
    })
  }, [agents, search])

  const getIntegrationLogo = (agent: TestAgent) => {
    const integration = integrations.find((i) => i.id === agent.voice_ai_integration_id)
    if (!integration?.platform) return null
    const platform = integration.platform as IntegrationPlatform
    const logo = getIntegrationPlatformLogo(platform)
    const label = getIntegrationPlatformLabel(platform)
    if (logo) {
      return <img src={logo} alt={label} className="h-4 w-4 object-contain shrink-0" title={label} />
    }
    return null
  }

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
            placeholder="Search ID or name…"
            className="w-full rounded-lg border border-gray-200 py-1.5 pl-8 pr-2 text-xs focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
        {agents.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={selectedAgents.size === agents.length && agents.length > 0}
              onChange={onSelectAll}
              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />
            Select all
          </label>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto p-2" aria-label="Agent list">
        {isLoading && <p className="px-2 py-4 text-sm text-gray-500">Loading…</p>}
        {!isLoading && agents.length === 0 && (
          <p className="px-2 py-4 text-sm text-gray-500">No agents yet.</p>
        )}
        {!isLoading && agents.length > 0 && filteredAgents.length === 0 && (
          <p className="px-2 py-4 text-sm text-gray-500">No matches.</p>
        )}
        {filteredAgents.map((agent) => {
          const isActive = selectedRouteId ? agentMatchesRoute(agent, selectedRouteId) : false
          return (
            <div
              key={agent.id}
              className={`mb-1 flex items-stretch gap-1 rounded-lg transition-colors ${
                isActive ? 'bg-primary-50 ring-1 ring-primary-200' : 'hover:bg-gray-50'
              }`}
            >
              <div className="flex items-center pl-2" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={selectedAgents.has(agent.id)}
                  onChange={(e) => onSelectAgentCheckbox(agent.id, e.target.checked)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  aria-label={`Select ${agent.name}`}
                />
              </div>
              <button
                type="button"
                onClick={() => onSelectAgent(agent)}
                className="flex-1 min-w-0 text-left px-2 py-2.5"
              >
                <div className="flex items-center gap-1.5">
                  {getIntegrationLogo(agent)}
                  <span className="font-mono text-xs font-semibold text-primary-600 truncate">
                    {agent.agent_id || agent.id.slice(0, 8)}
                  </span>
                </div>
                <p className="text-sm font-medium text-gray-900 truncate mt-0.5">{agent.name}</p>
                <p className="text-xs text-gray-500 mt-0.5 capitalize">
                  {agent.call_medium === 'phone_call' ? 'Phone' : 'Web'} · {agent.language.toUpperCase()} ·{' '}
                  {agent.call_type}
                </p>
              </button>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
