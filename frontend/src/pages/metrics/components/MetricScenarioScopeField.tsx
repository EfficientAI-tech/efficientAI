import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'

interface Props {
  mode: 'all' | 'selected'
  scenarioIds: string[]
  onModeChange: (mode: 'all' | 'selected') => void
  onScenarioIdsChange: (ids: string[]) => void
  agentId?: string | null
}

export default function MetricScenarioScopeField({
  mode,
  scenarioIds,
  onModeChange,
  onScenarioIdsChange,
  agentId,
}: Props) {
  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios', 'metric-scope', agentId ?? 'all'],
    queryFn: () => apiClient.listScenarios(0, 500, agentId ?? undefined),
  })

  return (
    <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5 space-y-3">
      <span className="block text-sm font-medium text-gray-700">Scenario scope</span>
      <div className="space-y-2">
        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="radio"
            name="metric-scenario-scope"
            checked={mode === 'all'}
            onChange={() => onModeChange('all')}
            className="mt-0.5 h-4 w-4 text-primary-600"
          />
          <span className="text-sm text-gray-800">
            <span className="font-medium">All scenarios</span>
            <span className="block text-xs text-gray-500 mt-0.5">
              Golden metric — evaluated on every simulation scenario.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="radio"
            name="metric-scenario-scope"
            checked={mode === 'selected'}
            onChange={() => onModeChange('selected')}
            className="mt-0.5 h-4 w-4 text-primary-600"
          />
          <span className="text-sm text-gray-800">
            <span className="font-medium">Selected scenarios</span>
            <span className="block text-xs text-gray-500 mt-0.5">
              Only scored when the trial uses one of these scenarios.
            </span>
          </span>
        </label>
      </div>
      {mode === 'selected' ? (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 space-y-1">
          {scenarios.length === 0 ? (
            <p className="text-xs text-gray-500 px-1">No scenarios in this workspace yet.</p>
          ) : (
            scenarios.map((s: { id: string; name: string }) => (
              <label key={s.id} className="flex items-center gap-2 px-1 py-0.5 text-sm">
                <input
                  type="checkbox"
                  checked={scenarioIds.includes(s.id)}
                  onChange={() =>
                    onScenarioIdsChange(
                      scenarioIds.includes(s.id)
                        ? scenarioIds.filter((id) => id !== s.id)
                        : [...scenarioIds, s.id],
                    )
                  }
                />
                <span className="truncate">{s.name}</span>
              </label>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}
