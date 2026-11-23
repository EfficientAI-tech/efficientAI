import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, FileText, Square, Trash2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import { downloadBlob } from '../../lib/download'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import { useToast } from '../../hooks/useToast'
import { formatDuration } from '../simulations/simulationFormat'
import RedTeamReportPanel from './RedTeamReportPanel'
import RedTeamSwarmTree from './RedTeamSwarmTree'
import RedTeamAttackDrawer from './RedTeamAttackDrawer'
import { RedTeamStatusChip, VerdictBadge } from './redTeamUi'
import { INTENSITY_LABELS, isRedTeamRunActive, redTeamRunTitle } from './redTeamFormat'

type RunTab = 'report' | 'swarm'

const RUN_TABS: { id: RunTab; label: string }[] = [
  { id: 'report', label: 'Report' },
  { id: 'swarm', label: 'Swarm' },
]

export default function RedTeamRunDetail() {
  const { runRef = '' } = useParams<{ runRef: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [activeTab, setActiveTab] = useState<RunTab | null>(null)
  const [selectedAttackId, setSelectedAttackId] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const { data: run, isLoading } = useQuery({
    queryKey: ['red-team-run', runRef],
    queryFn: () => apiClient.redTeam.getRun(runRef),
    enabled: Boolean(runRef),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && !isRedTeamRunActive(status) ? false : 4000
    },
  })

  const { data: entitlements } = useQuery({
    queryKey: ['red-team-entitlements'],
    queryFn: () => apiClient.redTeam.getEntitlements(),
    staleTime: 5 * 60 * 1000,
  })
  const familyNames = useMemo(
    () => new Map((entitlements?.catalog.families ?? []).map((f) => [f.id, f.name])),
    [entitlements],
  )

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['red-team-run', runRef] })
    queryClient.invalidateQueries({ queryKey: ['red-team-runs'] })
  }
  const stopMutation = useMutation({
    mutationFn: () => apiClient.redTeam.stopRun(runRef),
    onSuccess: () => {
      showToast('Stopping red team…')
      invalidate()
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Failed to stop run', 'error'),
  })
  const deleteMutation = useMutation({
    mutationFn: () => apiClient.redTeam.deleteRun(runRef),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['red-team-runs'] })
      showToast('Red team run deleted', 'success')
      navigate(`/agents/${run?.agent_id}?tab=red_team`)
    },
    onError: (err) => {
      setDeleteOpen(false)
      showToast(getApiErrorDetail(err) || 'Failed to delete run', 'error')
    },
  })
  const downloadMutation = useMutation({
    mutationFn: (format: 'pdf' | 'csv') => apiClient.redTeam.downloadReport(runRef, format),
    onSuccess: (blob, format) => downloadBlob(blob, `red-team-run-${run?.run_id ?? runRef}.${format}`),
    onError: (err) => showToast(getApiErrorDetail(err) || 'Download failed', 'error'),
  })

  if (isLoading) return <div className="p-6 text-sm text-gray-500">Loading run…</div>
  if (!run) return <div className="p-6 text-sm text-gray-500">Red team run not found.</div>

  const active = isRedTeamRunActive(run.status)
  // Default to the report once there is one, the live swarm while attacking.
  const tab: RunTab = activeTab ?? (run.report ? 'report' : 'swarm')
  const progress = run.max_attacks ? Math.min(100, (run.completed_attacks / run.max_attacks) * 100) : 0
  const knowledge = run.attacker_knowledge ?? []

  return (
    <div className="space-y-6 p-6">
      <div>
        <Link
          to={`/agents/${run.agent_id}?tab=red_team`}
          className="mb-2 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to agent
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-900">{redTeamRunTitle(run)}</h1>
              <RedTeamStatusChip status={run.status} />
              <VerdictBadge verdict={run.verdict} />
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Run <span className="font-mono">{run.run_id}</span> · {INTENSITY_LABELS[run.intensity] ?? run.intensity}{' '}
              · {run.modality} · {run.breached_attacks} breached of {run.completed_attacks} attacks ·{' '}
              {formatDuration(run.started_at, run.finished_at)}
            </p>
            {knowledge.length ? (
              <p className="mt-1 text-xs text-gray-500">
                Attacker knowledge: {knowledge.map((k) => k.label).join(', ')}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {active ? (
              <Button
                variant="outline"
                leftIcon={<Square className="h-4 w-4" />}
                onClick={() => stopMutation.mutate()}
                isLoading={stopMutation.isPending}
                disabled={run.cancel_requested}
              >
                {run.cancel_requested ? 'Stopping…' : 'Stop'}
              </Button>
            ) : (
              <>
                <Button
                  variant="outline"
                  leftIcon={<FileText className="h-4 w-4" />}
                  onClick={() => downloadMutation.mutate('pdf')}
                  isLoading={downloadMutation.isPending && downloadMutation.variables === 'pdf'}
                >
                  PDF report
                </Button>
                <Button
                  variant="outline"
                  leftIcon={<Download className="h-4 w-4" />}
                  onClick={() => downloadMutation.mutate('csv')}
                  isLoading={downloadMutation.isPending && downloadMutation.variables === 'csv'}
                >
                  CSV
                </Button>
              </>
            )}
            <Button
              variant="outline"
              leftIcon={<Trash2 className="h-4 w-4" />}
              onClick={() => setDeleteOpen(true)}
              isLoading={deleteMutation.isPending}
              className="text-red-700 hover:border-red-300 hover:bg-red-50"
            >
              Delete
            </Button>
          </div>
        </div>
        {active ? (
          <div className="mt-4">
            <div className="mb-1 flex justify-between text-xs text-gray-500">
              <span>
                {run.completed_attacks}/{run.max_attacks} attacks at most · {run.status === 'recon' ? 'running recon' : run.status}
              </span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="h-2 rounded-full bg-gray-100">
              <div className="h-2 rounded-full bg-primary-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        ) : null}
        {run.error_message ? (
          <pre className="mt-4 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            {run.error_message}
          </pre>
        ) : null}
      </div>

      <nav className="-mb-px flex space-x-6 border-b border-gray-200" aria-label="Red team run tabs">
        {RUN_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActiveTab(t.id)}
            className={`inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium transition-colors ${
              tab === t.id
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            }`}
          >
            {t.label}
            {t.id === 'swarm' ? (
              <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-gray-600">
                {run.attacks.length}
              </span>
            ) : null}
          </button>
        ))}
      </nav>

      {tab === 'report' ? (
        <RedTeamReportPanel run={run} />
      ) : (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <RedTeamSwarmTree
            attacks={run.attacks}
            selectedAttackId={selectedAttackId}
            onSelect={(a) => setSelectedAttackId(a.id)}
            familyNames={familyNames}
          />
        </section>
      )}

      <RedTeamAttackDrawer
        runRef={runRef}
        attackId={selectedAttackId}
        familyNames={familyNames}
        onClose={() => setSelectedAttackId(null)}
      />
      <ConfirmModal
        isOpen={deleteOpen}
        title="Delete red team run"
        description={
          active
            ? 'This run is still active. Deleting it stops the run and removes every attack and its report. This cannot be undone.'
            : 'This removes the run with every attack and its report. This cannot be undone.'
        }
        confirmLabel="Delete run"
        variant="danger"
        isLoading={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
        onCancel={() => setDeleteOpen(false)}
      />
      <ToastContainer />
    </div>
  )
}
