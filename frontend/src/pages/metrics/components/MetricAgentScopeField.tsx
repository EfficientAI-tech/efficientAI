import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'

interface Props {
  mode: 'all' | 'selected'
  agentIds: string[]
  onModeChange: (mode: 'all' | 'selected') => void
  onAgentIdsChange: (ids: string[]) => void
}

export default function MetricAgentScopeField({
  mode,
  agentIds,
  onModeChange,
  onAgentIdsChange,
}: Props) {
  const { data: agents = [] } = useQuery({
    queryKey: ['agents', 'metric-scope'],
    queryFn: () => apiClient.listAgents(0, 500),
  })

  return (
    <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5 space-y-3">
      <span className="block text-sm font-medium text-gray-700">Agent scope</span>
      <div className="space-y-2">
        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="radio"
            name="metric-agent-scope"
            checked={mode === 'all'}
            onChange={() => onModeChange('all')}
            className="mt-0.5 h-4 w-4 text-primary-600"
          />
          <span className="text-sm text-gray-800">
            <span className="font-medium">All agents</span>
            <span className="block text-xs text-gray-500 mt-0.5">
              Golden metric — evaluated for every agent in simulation runs.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="radio"
            name="metric-agent-scope"
            checked={mode === 'selected'}
            onChange={() => onModeChange('selected')}
            className="mt-0.5 h-4 w-4 text-primary-600"
          />
          <span className="text-sm text-gray-800">
            <span className="font-medium">Selected agents</span>
            <span className="block text-xs text-gray-500 mt-0.5">
              Only scored when the trial uses one of these agents.
            </span>
          </span>
        </label>
      </div>
      {mode === 'selected' ? (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 space-y-1">
          {agents.length === 0 ? (
            <p className="text-xs text-gray-500 px-1">No agents in this workspace yet.</p>
          ) : (
            agents.map((a: { id: string; name: string }) => (
              <label key={a.id} className="flex items-center gap-2 px-1 py-0.5 text-sm">
                <input
                  type="checkbox"
                  checked={agentIds.includes(a.id)}
                  onChange={() =>
                    onAgentIdsChange(
                      agentIds.includes(a.id)
                        ? agentIds.filter((id) => id !== a.id)
                        : [...agentIds, a.id],
                    )
                  }
                />
                <span className="truncate">{a.name}</span>
              </label>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}
