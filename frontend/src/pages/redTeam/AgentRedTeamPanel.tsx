import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ShieldAlert, Swords, Trash2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import { useToast } from '../../hooks/useToast'
import type { RedTeamKnowledgeItem, RedTeamRun } from '../../types/redTeam'
import LaunchRedTeamModal from './LaunchRedTeamModal'
import { RedTeamStatusChip, VerdictBadge } from './redTeamUi'
import { INTENSITY_LABELS, isRedTeamRunActive } from './redTeamFormat'

interface Props {
  agent: {
    id: string
    name: string
    call_medium?: string | null
  }
}

function knowledgeKey(items: RedTeamKnowledgeItem[] | null | undefined): string {
  return JSON.stringify(
    (items ?? []).map((k) => [k.label.trim().toLowerCase(), k.value.trim()]).sort(),
  )
}

/** Reports are only comparable when intensity and attacker knowledge match. */
function comparabilityWarning(runs: RedTeamRun[]): string | null {
  const completed = runs
    .filter((r) => r.status === 'completed')
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  if (completed.length < 2) return null
  const [latest, previous] = completed
  const reasons: string[] = []
  if (latest.intensity !== previous.intensity) {
    reasons.push(`intensity (${INTENSITY_LABELS[latest.intensity]} vs ${INTENSITY_LABELS[previous.intensity]})`)
  }
  if (knowledgeKey(latest.attacker_knowledge) !== knowledgeKey(previous.attacker_knowledge)) {
    reasons.push('attacker knowledge')
  }
  if (!reasons.length) return null
  return `Runs ${latest.run_id} and ${previous.run_id} used a different ${reasons.join(' and ')}, so their reports are not comparable.`
}

export default function AgentRedTeamPanel({ agent }: Props) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [modalOpen, setModalOpen] = useState(false)
  const [runToDelete, setRunToDelete] = useState<RedTeamRun | null>(null)

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ['red-team-runs', agent.id],
    queryFn: () => apiClient.redTeam.listRuns(agent.id),
    refetchInterval: (query) => (query.state.data?.some((r) => isRedTeamRunActive(r.status)) ? 5000 : false),
  })

  const deleteMutation = useMutation({
    mutationFn: (runRef: string) => apiClient.redTeam.deleteRun(runRef),
    onSuccess: () => {
      setRunToDelete(null)
      queryClient.invalidateQueries({ queryKey: ['red-team-runs', agent.id] })
      showToast('Red team run deleted', 'success')
    },
    onError: (err) => {
      setRunToDelete(null)
      showToast(getApiErrorDetail(err) || 'Failed to delete run', 'error')
    },
  })

  const warning = useMemo(() => comparabilityWarning(runs), [runs])

  return (
    <div className="space-y-4">
      <ToastContainer />
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Red teaming</h3>
          <p className="text-sm text-gray-500">
            Adversarial callers probe {agent.name}, then escalate attacks across social engineering, prompt
            injection and harmful content. Each run ends with a verdict mapped to the OWASP LLM Top 10.
          </p>
        </div>
        <Button variant="primary" leftIcon={<Swords className="h-4 w-4" />} onClick={() => setModalOpen(true)}>
          Launch red team
        </Button>
      </div>

      {warning ? (
        <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {warning}
        </p>
      ) : null}

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading runs…</p>
      ) : runs.length === 0 ? (
        <div className="flex flex-col items-center rounded-lg border border-dashed border-gray-300 px-6 py-10 text-center">
          <ShieldAlert className="mb-2 h-8 w-8 text-gray-400" />
          <p className="text-sm font-medium text-gray-900">No red team runs yet</p>
          <p className="mt-1 text-sm text-gray-500">
            Launch a Quick run while iterating, then a Thorough run for the report you share.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Run</th>
                <th className="px-3 py-2">Intensity</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Verdict</th>
                <th className="px-3 py-2 text-right">Breached / attacks</th>
                <th className="px-3 py-2">Started</th>
                <th className="w-12 px-3 py-2" aria-label="Actions" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {runs.map((run) => (
                <tr
                  key={run.id}
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => navigate(`/red-team/${run.run_id}`)}
                >
                  <td className="px-3 py-2">
                    <span className="font-mono text-xs font-semibold text-primary-600">{run.run_id}</span>
                    {run.name ? <span className="ml-2 text-gray-900">{run.name}</span> : null}
                  </td>
                  <td className="px-3 py-2 text-gray-700">
                    {INTENSITY_LABELS[run.intensity] ?? run.intensity}
                    <span className="ml-1 text-[11px] text-gray-500">· {run.modality}</span>
                  </td>
                  <td className="px-3 py-2">
                    <RedTeamStatusChip status={run.status} />
                  </td>
                  <td className="px-3 py-2">
                    <VerdictBadge verdict={run.verdict} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                    <span className={run.breached_attacks ? 'font-semibold text-red-700' : ''}>
                      {run.breached_attacks}
                    </span>
                    {' / '}
                    {run.completed_attacks}
                    {isRedTeamRunActive(run.status) ? (
                      <span className="text-gray-400"> of ≤{run.max_attacks}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {new Date(run.started_at ?? run.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      title="Delete run"
                      className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-700"
                      onClick={(e) => {
                        e.stopPropagation()
                        setRunToDelete(run)
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmModal
        isOpen={runToDelete !== null}
        title="Delete red team run"
        description={
          runToDelete && isRedTeamRunActive(runToDelete.status)
            ? `Run ${runToDelete.run_id} is still active. Deleting it stops the run and removes every attack and its report. This cannot be undone.`
            : `This removes run ${runToDelete?.run_id ?? ''} with every attack and its report. This cannot be undone.`
        }
        confirmLabel="Delete run"
        variant="danger"
        isLoading={deleteMutation.isPending}
        onConfirm={() => runToDelete && deleteMutation.mutate(runToDelete.run_id)}
        onCancel={() => setRunToDelete(null)}
      />

      <LaunchRedTeamModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        agent={agent}
        onLaunched={(run) => {
          setModalOpen(false)
          queryClient.invalidateQueries({ queryKey: ['red-team-runs', agent.id] })
          navigate(`/red-team/${run.run_id}`)
        }}
      />
    </div>
  )
}
