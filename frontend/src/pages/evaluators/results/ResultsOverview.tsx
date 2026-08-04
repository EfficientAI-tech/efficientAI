import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import ResultsCountCards from './ResultsCountCards'
import ResultsHierarchyNav from './ResultsHierarchyNav'
import { Bot, Layers } from 'lucide-react'
import { formatTimestamp } from './resultsFormatting'

export default function ResultsOverview() {
  const { data, isLoading } = useQuery({
    queryKey: ['evaluator-results-overview'],
    queryFn: () => apiClient.getEvaluatorResultsOverview(),
  })

  return (
    <div className="space-y-6">
      <ResultsHierarchyNav crumbs={[{ label: 'Evaluation Results' }]} />
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluation Results</h1>
          <p className="mt-2 text-sm text-gray-600">
            Browse outcomes by agent, evaluator suite, and scenario
          </p>
        </div>
        <Link
          to="/results/unassigned"
          className="text-sm font-medium text-primary-600 hover:text-primary-800"
        >
          Unassigned runs
        </Link>
      </div>

      {isLoading || !data ? (
        <p className="text-gray-500">Loading overview…</p>
      ) : (
        <>
          <ResultsCountCards counts={data.workspace_counts} />
          {data.unassigned.counts.total > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              {data.unassigned.counts.total} run(s) are not linked to an evaluator suite.{' '}
              <Link to="/results/unassigned" className="font-semibold underline">
                View unassigned
              </Link>
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.agents.map((agent) => (
              <Link
                key={agent.agent_id}
                to={`/results/agents/${agent.agent_id}`}
                className="group rounded-xl border border-gray-200 bg-white p-5 shadow-sm hover:border-primary-300 hover:shadow-md transition-all"
              >
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-primary-50 p-2">
                    <Bot className="w-5 h-5 text-primary-600" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h2 className="font-semibold text-gray-900 truncate group-hover:text-primary-700">
                      {agent.agent_name}
                    </h2>
                    <p className="text-xs text-gray-500 mt-1">
                      {agent.suites?.length ?? 0} suite(s) · {agent.counts.total} run(s)
                    </p>
                    {agent.counts.last_run_at && (
                      <p className="text-xs text-gray-400 mt-2">
                        Last run {formatTimestamp(agent.counts.last_run_at)}
                      </p>
                    )}
                  </div>
                </div>
                <div className="mt-4 flex gap-3 text-xs text-gray-600">
                  <span className="text-emerald-700">{agent.counts.completed} done</span>
                  <span className="text-rose-700">{agent.counts.failed} failed</span>
                  <span className="text-blue-700">{agent.counts.in_progress} active</span>
                </div>
              </Link>
            ))}
          </div>
          {data.agents.length === 0 && (
            <div className="text-center py-16 text-gray-500">
              <Layers className="w-10 h-10 mx-auto text-gray-300 mb-3" />
              <p>No suite-backed evaluation runs yet.</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
