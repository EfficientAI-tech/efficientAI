import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FlaskConical, Plus } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import NewSimulationRunModal from './NewSimulationRunModal'
import { RunStatusChip } from './simulationUi'
import { formatDuration, formatPct, formatScore, isRunActive } from './simulationFormat'

interface Props {
  agent: {
    id: string
    name: string
    call_medium?: string | null
    chat_connection_type?: string | null
    main_llm_model?: string | null
    test_llm_model?: string | null
  }
}

export default function AgentSimulationsPanel({ agent }: Props) {
  const navigate = useNavigate()
  const [modalOpen, setModalOpen] = useState(false)

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ['simulation-runs', agent.id],
    queryFn: () => apiClient.listSimulationRuns(agent.id),
    refetchInterval: (query) => (query.state.data?.some((r) => isRunActive(r.status)) ? 5000 : false),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Simulation runs</h3>
          <p className="text-sm text-gray-500">
            Run your synthetic scenarios against this agent with Harbor and see how every conversation scored.
          </p>
        </div>
        <Button variant="primary" leftIcon={<Plus className="h-4 w-4" />} onClick={() => setModalOpen(true)}>
          New run
        </Button>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading runs…</p>
      ) : runs.length === 0 ? (
        <div className="flex flex-col items-center rounded-lg border border-dashed border-gray-300 px-6 py-10 text-center">
          <FlaskConical className="mb-2 h-8 w-8 text-gray-400" />
          <p className="text-sm font-medium text-gray-900">No simulation runs yet</p>
          <p className="mt-1 text-sm text-gray-500">
            Start a run to simulate every scenario × persona against {agent.name}.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Run</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Progress</th>
                <th className="px-3 py-2 text-right">Pass rate</th>
                <th className="px-3 py-2 text-right">Mean score</th>
                <th className="px-3 py-2">Production model</th>
                <th className="px-3 py-2">Started</th>
                <th className="px-3 py-2 text-right">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {runs.map((run) => (
                <tr
                  key={run.id}
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => navigate(`/simulations/${run.run_id}`)}
                >
                  <td className="px-3 py-2">
                    <span className="font-mono text-xs font-semibold text-primary-600">{run.run_id}</span>
                    {run.name ? <span className="ml-2 text-gray-900">{run.name}</span> : null}
                  </td>
                  <td className="px-3 py-2">
                    <RunStatusChip status={run.status} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                    {run.completed_trials + run.failed_trials}/{run.expected_trials}
                    {run.failed_trials ? <span className="ml-1 text-xs text-red-600">({run.failed_trials} errored)</span> : null}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatPct(run.summary?.pass_rate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatScore(run.summary?.mean_reward)}</td>
                  <td className="px-3 py-2 text-gray-700">
                    {run.production_llm_model ? `${run.production_llm_provider}/${run.production_llm_model}` : 'Agent default'}
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-500">
                    {formatDuration(run.started_at, run.finished_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <NewSimulationRunModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        agent={agent}
        onCreated={(run) => {
          setModalOpen(false)
          navigate(`/simulations/${run.run_id}`)
        }}
      />
    </div>
  )
}
