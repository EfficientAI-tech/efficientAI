import { useState, useMemo, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { apiClient, EvaluatorSuite } from '../../../lib/api'
import Button from '../../../components/Button'
import ConfirmModal from '../../../components/ConfirmModal'
import {
  Plus,
  Trash2,
  Play,
  CheckSquare,
  Square,
  FlaskConical,
  Loader2,
  Layers,
  PhoneIncoming,
  PhoneOutgoing,
  ChevronRight,
} from 'lucide-react'
import { useToast } from '../../../hooks/useToast'
import { useWalkthroughSectionState } from '../../../context/WalkthroughContext'
import WalkthroughToggleButton from '../../../components/walkthrough/WalkthroughToggleButton'
import { formatSuitePersonaLabel } from '../components/evaluatorSuitePersonas'
import EvaluatorSuiteWizard from '../components/EvaluatorSuiteWizard'
import EvaluatorSmartRunModal from '../components/EvaluatorSmartRunModal'
import { CallTypeBadge, StatCard } from '../components/evaluatorUi'
import { countDisplayMetrics, type MetricRow } from '../components/metricSelectionUtils'

export default function EvaluateTestAgents() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [selectedSuiteIds, setSelectedSuiteIds] = useState<Set<string>>(new Set())
  const [showRunModal, setShowRunModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [collapsedAgentIds, setCollapsedAgentIds] = useState<Set<string>>(new Set())

  useWalkthroughSectionState(
    'evaluators',
    { showCreateModal, showRunModal },
    [showCreateModal, showRunModal],
  )

  const { data: suites = [], isLoading } = useQuery({
    queryKey: ['evaluator-suites'],
    queryFn: () => apiClient.listEvaluatorSuites(),
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', 'agent'],
    queryFn: () => apiClient.listMetrics('agent', true),
  })

  const metricRows = metrics as MetricRow[]

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof apiClient.createEvaluatorSuite>[0]) =>
      apiClient.createEvaluatorSuite(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-suites'] })
      setShowCreateModal(false)
      showToast('Evaluator suite created', 'success')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      showToast(typeof detail === 'string' ? detail : 'Failed to create suite', 'error')
    },
  })

  const stats = useMemo(() => {
    const inbound = suites.filter((s) => s.agent_call_type === 'inbound').length
    const outbound = suites.filter(
      (s) => s.agent_call_medium === 'phone_call' && s.agent_call_type !== 'inbound',
    ).length
    const web = suites.filter((s) => s.agent_call_medium === 'web_call').length
    const combinations = suites.reduce((sum, s) => sum + s.combination_count, 0)
    return { total: suites.length, inbound, outbound, web, combinations }
  }, [suites])

  const sortedSuites = useMemo(() => {
    return [...suites].sort((a, b) => {
      const agentCmp = (a.agent_name || '').localeCompare(b.agent_name || '')
      if (agentCmp !== 0) return agentCmp
      if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })
  }, [suites])

  const suiteGroups = useMemo(() => {
    const map = new Map<string, EvaluatorSuite[]>()
    for (const suite of sortedSuites) {
      const list = map.get(suite.agent_id) ?? []
      list.push(suite)
      map.set(suite.agent_id, list)
    }
    return Array.from(map.entries()).map(([agentId, groupSuites]) => ({
      agentId,
      agentName: groupSuites[0]?.agent_name || 'Unknown agent',
      suites: groupSuites,
    }))
  }, [sortedSuites])

  const toggleAgentCollapsed = (agentId: string) => {
    setCollapsedAgentIds((prev) => {
      const next = new Set(prev)
      if (next.has(agentId)) next.delete(agentId)
      else next.add(agentId)
      return next
    })
  }

  const toggleSuite = (id: string) => {
    setSelectedSuiteIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    const ids = suites.map((s) => s.id)
    const allSelected = ids.length > 0 && ids.every((id) => selectedSuiteIds.has(id))
    setSelectedSuiteIds(allSelected ? new Set() : new Set(ids))
  }

  const selectedSuites = suites.filter((s) => selectedSuiteIds.has(s.id))
  const selectedSuite = selectedSuites.length === 1 ? selectedSuites[0] : null
  const selectedIsInbound = selectedSuite?.agent_call_type === 'inbound'

  const handleDeleteSelected = async () => {
    setIsDeleting(true)
    const ids = Array.from(selectedSuiteIds)
    try {
      await Promise.all(ids.map((id) => apiClient.deleteEvaluatorSuite(id)))
      queryClient.invalidateQueries({ queryKey: ['evaluator-suites'] })
      setSelectedSuiteIds(new Set())
      showToast(`Deleted ${ids.length} suite${ids.length !== 1 ? 's' : ''}`, 'success')
    } catch (err: any) {
      showToast(err?.response?.data?.detail || 'Delete failed', 'error')
    } finally {
      setIsDeleting(false)
      setShowDeleteModal(false)
    }
  }

  return (
    <div className="space-y-6">
      <ToastContainer />

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-gray-900">Evaluators</h1>
          <p className="mt-2 text-sm text-gray-600">
            Configure agent + persona + scenario combinations for automated post-call evaluation
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-2">
          <AnimatePresence>
            {selectedSuiteIds.size > 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="flex flex-wrap items-center gap-2"
              >
                {!selectedIsInbound && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => setShowRunModal(true)}
                    disabled={selectedSuiteIds.size !== 1}
                    title={selectedSuiteIds.size !== 1 ? 'Select exactly one suite to run' : undefined}
                    leftIcon={<Play className="h-4 w-4" />}
                  >
                    Run
                  </Button>
                )}
                {selectedIsInbound && (
                  <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-3 py-1.5">
                    Inbound — runs via incoming calls
                  </span>
                )}
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => setShowDeleteModal(true)}
                  leftIcon={<Trash2 className="h-4 w-4" />}
                >
                  Delete ({selectedSuiteIds.size})
                </Button>
              </motion.div>
            )}
          </AnimatePresence>
          <WalkthroughToggleButton />
          <Button
            variant="primary"
            onClick={() => setShowCreateModal(true)}
            leftIcon={<Plus className="h-5 w-5" />}
          >
            Create Suite
          </Button>
        </div>
      </div>

      {/* Summary stats */}
      {!isLoading && suites.length > 0 && (
        <motion.div
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <StatCard
            label="Total Suites"
            value={stats.total}
            accentClass="text-gray-900"
            iconBgClass="bg-slate-100"
            iconClass="text-slate-600"
            icon={<FlaskConical className="w-5 h-5" />}
          />
          <StatCard
            label="Combinations"
            value={stats.combinations}
            accentClass="text-indigo-600"
            iconBgClass="bg-indigo-50"
            iconClass="text-indigo-500"
            icon={<Layers className="w-5 h-5" />}
          />
          <StatCard
            label="Outbound"
            value={stats.outbound + stats.web}
            accentClass="text-emerald-600"
            iconBgClass="bg-emerald-50"
            iconClass="text-emerald-500"
            icon={<PhoneOutgoing className="w-5 h-5" />}
          />
          <StatCard
            label="Inbound"
            value={stats.inbound}
            accentClass="text-amber-600"
            iconBgClass="bg-amber-50"
            iconClass="text-amber-500"
            icon={<PhoneIncoming className="w-5 h-5" />}
          />
        </motion.div>
      )}

      {/* Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FlaskConical className="h-5 w-5 text-primary-600" />
            <h2 className="text-lg font-semibold text-gray-900">Evaluator Suites</h2>
            {suites.length > 0 && (
              <span className="px-2 py-0.5 text-xs font-medium text-primary-700 bg-primary-50 rounded-full border border-primary-100">
                {suites.length}
              </span>
            )}
            {suites.length > 0 && suiteGroups.some((g) => g.suites.length > 1) && (
              <button
                type="button"
                className="text-xs font-medium text-primary-600 hover:text-primary-800"
                onClick={() => {
                  const multiIds = suiteGroups.filter((g) => g.suites.length > 1).map((g) => g.agentId)
                  const allCollapsed = multiIds.every((id) => collapsedAgentIds.has(id))
                  setCollapsedAgentIds(allCollapsed ? new Set() : new Set(multiIds))
                }}
              >
                {suiteGroups.filter((g) => g.suites.length > 1).every((g) => collapsedAgentIds.has(g.agentId))
                  ? 'Expand all agents'
                  : 'Collapse all agents'}
              </button>
            )}
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-64 text-gray-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading suites…
          </div>
        ) : suites.length === 0 ? (
          <div className="p-12 text-center">
            <FlaskConical className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No evaluator suites yet</h3>
            <p className="text-gray-500 mb-6 max-w-md mx-auto">
              Create a suite to pair an agent, persona, and scenarios for automated evaluation runs.
            </p>
            <Button
              variant="primary"
              onClick={() => setShowCreateModal(true)}
              leftIcon={<Plus className="h-5 w-5" />}
            >
              Create your first suite
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 w-10">
                    <button type="button" onClick={toggleSelectAll} className="text-gray-400 hover:text-primary-600">
                      {suites.every((s) => selectedSuiteIds.has(s.id)) ? (
                        <CheckSquare className="w-5 h-5 text-primary-600" />
                      ) : (
                        <Square className="w-5 h-5" />
                      )}
                    </button>
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Agent</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Persona</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Scenarios</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Metrics</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {suiteGroups.map((group) => {
                  const multi = group.suites.length > 1
                  const collapsed = multi && collapsedAgentIds.has(group.agentId)
                  const activeSuite = group.suites.find((s) => s.is_active) ?? group.suites[0]

                  const renderSuiteRow = (suite: EvaluatorSuite) => {
                    const cellClass = multi ? 'py-4 pl-8 pr-6' : 'px-6 py-4'

                    return (
                    <tr
                      key={suite.id}
                      className={`hover:bg-gray-50 transition-colors ${selectedSuiteIds.has(suite.id) ? 'bg-primary-50/40' : ''}`}
                    >
                      <td className={cellClass}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleSuite(suite.id)
                          }}
                          className="text-gray-400 hover:text-primary-600"
                        >
                          {selectedSuiteIds.has(suite.id) ? (
                            <CheckSquare className="w-5 h-5 text-primary-600" />
                          ) : (
                            <Square className="w-5 h-5" />
                          )}
                        </button>
                      </td>
                      <td className={cellClass}>
                        <button
                          type="button"
                          onClick={() => navigate(`/evaluate-test-agents/${suite.id}`)}
                          className="text-sm font-medium text-primary-700 hover:text-primary-800 hover:underline text-left"
                        >
                          {suite.name || `${suite.agent_name || 'Suite'} · ${suite.persona_name || 'Persona'}`}
                        </button>
                      </td>
                      <td className={`${cellClass} text-sm text-gray-900`}>
                        {suite.agent_name || group.agentName || '—'}
                      </td>
                      <td className={`${cellClass} text-sm text-gray-900`}>{formatSuitePersonaLabel(suite)}</td>
                      <td className={cellClass}>
                        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-100">
                          {suite.combination_count}
                        </span>
                      </td>
                      <td className={cellClass}>
                        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-gray-50 text-gray-700 border border-gray-100">
                          {(() => {
                            const count = countDisplayMetrics(suite.metric_ids, metricRows)
                            return count != null ? `${count} selected` : 'All'
                          })()}
                        </span>
                      </td>
                      <td className={cellClass}>
                        <CallTypeBadge medium={suite.agent_call_medium} callType={suite.agent_call_type} />
                      </td>
                      <td className={cellClass}>
                        {suite.is_active ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                            Active
                          </span>
                        ) : suite.agent_call_type === 'inbound' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                            Inactive
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                    )
                  }

                  if (!multi) {
                    return renderSuiteRow(group.suites[0])
                  }

                  const groupAllSelected = group.suites.every((s) => selectedSuiteIds.has(s.id))
                  const groupSomeSelected = group.suites.some((s) => selectedSuiteIds.has(s.id))

                  return (
                    <Fragment key={group.agentId}>
                      <tr
                        className="bg-slate-50/90 hover:bg-slate-100/90 cursor-pointer border-t border-slate-200"
                        onClick={() => toggleAgentCollapsed(group.agentId)}
                      >
                        <td className="px-6 py-3">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedSuiteIds((prev) => {
                                const next = new Set(prev)
                                if (groupAllSelected) {
                                  group.suites.forEach((s) => next.delete(s.id))
                                } else {
                                  group.suites.forEach((s) => next.add(s.id))
                                }
                                return next
                              })
                            }}
                            className="text-gray-400 hover:text-primary-600"
                          >
                            {groupAllSelected ? (
                              <CheckSquare className="w-5 h-5 text-primary-600" />
                            ) : groupSomeSelected ? (
                              <CheckSquare className="w-5 h-5 text-primary-400 opacity-60" />
                            ) : (
                              <Square className="w-5 h-5" />
                            )}
                          </button>
                        </td>
                        <td className="px-6 py-3" colSpan={2}>
                          <div className="flex items-center gap-2 min-w-0">
                            <ChevronRight
                              className={`h-4 w-4 text-gray-500 shrink-0 transition-transform ${collapsed ? '' : 'rotate-90'}`}
                            />
                            <span className="text-sm font-semibold text-gray-900 truncate">{group.agentName}</span>
                            <span className="text-xs text-gray-500 shrink-0">
                              {group.suites.length} suites
                            </span>
                          </div>
                          {collapsed && (
                            <p className="text-xs text-gray-500 mt-1 pl-8 truncate">
                              Active: {activeSuite.name || activeSuite.persona_name || '—'}
                              {activeSuite.is_active ? '' : ' (none marked active)'}
                            </p>
                          )}
                        </td>
                        <td className="px-6 py-3 text-sm text-gray-600">
                          {collapsed ? activeSuite.persona_name || '—' : ''}
                        </td>
                        <td className="px-6 py-3">
                          {collapsed && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-100">
                              {activeSuite.combination_count}
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-3" colSpan={3}>
                          {collapsed && (
                            <div className="flex flex-wrap items-center gap-2">
                              <CallTypeBadge
                                medium={activeSuite.agent_call_medium}
                                callType={activeSuite.agent_call_type}
                              />
                              {activeSuite.is_active && (
                                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                                  Active
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                      {!collapsed && group.suites.map((suite) => renderSuiteRow(suite))}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <EvaluatorSuiteWizard
        open={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        isSubmitting={createMutation.isPending}
        onSubmit={(payload) => createMutation.mutate(payload)}
      />

      <EvaluatorSmartRunModal
        open={showRunModal}
        onClose={() => setShowRunModal(false)}
        suites={selectedSuites}
        showToast={showToast}
      />

      <ConfirmModal
        isOpen={showDeleteModal}
        title={`Delete ${selectedSuiteIds.size} suite${selectedSuiteIds.size !== 1 ? 's' : ''}?`}
        description="Historical evaluation results are preserved. This action cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDeleteSelected}
        onCancel={() => setShowDeleteModal(false)}
        isLoading={isDeleting}
        variant="danger"
      />
    </div>
  )
}
