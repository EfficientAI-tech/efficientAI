import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
import ConfirmModal from '../components/ConfirmModal'
import { Plus, Edit, Trash2, X, Play, Pause, Clock, Calendar, Globe, Info } from 'lucide-react'
import { CronJobStatus } from '../types/api'
import { useToast } from '../hooks/useToast'

// Types
interface CronJob {
  id: string
  organization_id: string
  name: string
  cron_expression: string
  timezone: string
  max_runs: number
  current_runs: number
  evaluator_ids: string[]
  status: CronJobStatus
  next_run_at?: string | null
  last_run_at?: string | null
  created_at: string
  updated_at: string
}

interface Evaluator {
  id: string
  evaluator_id: string
  agent_id: string
  persona_id: string
  scenario_id: string
  tags?: string[]
}

// Preset cron expressions
const CRON_PRESETS = [
  { value: '0 * * * *', label: 'Every hour', description: 'Runs at minute 0 of every hour' },
  { value: '0 */2 * * *', label: 'Every 2 hours', description: 'Runs every 2 hours' },
  { value: '0 */6 * * *', label: 'Every 6 hours', description: 'Runs at 0:00, 6:00, 12:00, 18:00' },
  { value: '0 0 * * *', label: 'Daily at midnight', description: 'Runs once a day at 00:00' },
  { value: '0 9 * * *', label: 'Daily at 9 AM', description: 'Runs once a day at 09:00' },
  { value: '0 0 * * 1', label: 'Weekly (Monday)', description: 'Runs every Monday at 00:00' },
  { value: '0 9 * * 1-5', label: 'Weekdays at 9 AM', description: 'Runs Mon-Fri at 09:00' },
  { value: '0 0 1 * *', label: 'Monthly', description: 'Runs on the 1st of every month' },
  { value: 'custom', label: 'Custom', description: 'Enter your own cron expression' },
]

// Common timezones
const TIMEZONES = [
  { value: 'UTC', label: 'UTC' },
  { value: 'America/New_York', label: 'Eastern Time (US)' },
  { value: 'America/Chicago', label: 'Central Time (US)' },
  { value: 'America/Denver', label: 'Mountain Time (US)' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (US)' },
  { value: 'Europe/London', label: 'London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Paris (CET/CEST)' },
  { value: 'Europe/Berlin', label: 'Berlin (CET/CEST)' },
  { value: 'Asia/Tokyo', label: 'Tokyo (JST)' },
  { value: 'Asia/Shanghai', label: 'Shanghai (CST)' },
  { value: 'Asia/Kolkata', label: 'India (IST)' },
  { value: 'Asia/Singapore', label: 'Singapore (SGT)' },
  { value: 'Australia/Sydney', label: 'Sydney (AEST/AEDT)' },
]

export default function CronJobs() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [cronJobToDelete, setCronJobToDelete] = useState<CronJob | null>(null)
  const [editingCronJob, setEditingCronJob] = useState<CronJob | null>(null)
  const [selectedPreset, setSelectedPreset] = useState('0 0 * * *')
  const [formData, setFormData] = useState({
    name: '',
    cron_expression: '0 0 * * *',
    timezone: 'UTC',
    max_runs: 10,
    evaluator_ids: [] as string[],
  })

  // Fetch cron jobs - handle case where backend endpoint doesn't exist yet
  const { data: cronJobs = [], isLoading, isError } = useQuery({
    queryKey: ['cron-jobs'],
    queryFn: () => apiClient.listCronJobs(),
    retry: false, // Don't retry if endpoint doesn't exist
  })

  // Fetch evaluators for selection
  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
  })

  // Fetch agents, personas, and scenarios for display names
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: personas = [] } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  const createMutation = useMutation({
    mutationFn: (data: any) => apiClient.createCronJob(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cron-jobs'] })
      closeModal()
      showToast('Cron job created successfully', 'success')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to create cron job'
      showToast(message, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) =>
      apiClient.updateCronJob(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cron-jobs'] })
      closeModal()
      showToast('Cron job updated successfully', 'success')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to update cron job'
      showToast(message, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteCronJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cron-jobs'] })
      setShowDeleteModal(false)
      setCronJobToDelete(null)
      showToast('Cron job deleted successfully', 'success')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to delete cron job'
      showToast(message, 'error')
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (id: string) => apiClient.toggleCronJobStatus(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cron-jobs'] })
      showToast('Cron job status updated', 'success')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to toggle cron job status'
      showToast(message, 'error')
    },
  })

  const getAgentName = (agentId: string) => {
    const agent = agents.find((a: any) => a.id === agentId || a.agent_id === agentId)
    return agent?.name || 'Unknown Agent'
  }

  const getPersonaName = (personaId: string) => {
    const persona = personas.find((p: any) => p.id === personaId)
    return persona?.name || 'Unknown Persona'
  }

  const getScenarioName = (scenarioId: string) => {
    const scenario = scenarios.find((s: any) => s.id === scenarioId)
    return scenario?.name || 'Unknown Scenario'
  }

  const getEvaluatorDisplayName = (evaluator: Evaluator) => {
    const agentName = getAgentName(evaluator.agent_id)
    const personaName = getPersonaName(evaluator.persona_id)
    const scenarioName = getScenarioName(evaluator.scenario_id)
    return `${agentName} / ${personaName} / ${scenarioName}`
  }

  const resetForm = () => {
    setFormData({
      name: '',
      cron_expression: '0 0 * * *',
      timezone: 'UTC',
      max_runs: 10,
      evaluator_ids: [],
    })
    setSelectedPreset('0 0 * * *')
  }

  const closeModal = () => {
    setShowCreateModal(false)
    setEditingCronJob(null)
    resetForm()
  }

  const handleEdit = (cronJob: CronJob) => {
    setEditingCronJob(cronJob)
    setFormData({
      name: cronJob.name,
      cron_expression: cronJob.cron_expression,
      timezone: cronJob.timezone,
      max_runs: cronJob.max_runs,
      evaluator_ids: cronJob.evaluator_ids || [],
    })
    // Check if the cron expression matches a preset
    const matchingPreset = CRON_PRESETS.find(p => p.value === cronJob.cron_expression)
    setSelectedPreset(matchingPreset ? cronJob.cron_expression : 'custom')
    setShowCreateModal(true)
  }

  const handlePresetChange = (presetValue: string) => {
    setSelectedPreset(presetValue)
    if (presetValue !== 'custom') {
      setFormData(prev => ({ ...prev, cron_expression: presetValue }))
    }
  }

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      alert('Please enter a cron job name')
      return
    }
    if (!formData.cron_expression.trim()) {
      alert('Please enter a cron expression')
      return
    }
    if (formData.evaluator_ids.length === 0) {
      alert('Please select at least one evaluator')
      return
    }
    if (formData.max_runs < 1) {
      alert('Number of runs must be at least 1')
      return
    }

    const payload = {
      name: formData.name,
      cron_expression: formData.cron_expression,
      timezone: formData.timezone,
      max_runs: formData.max_runs,
      evaluator_ids: formData.evaluator_ids,
    }

    if (editingCronJob) {
      updateMutation.mutate({ id: editingCronJob.id, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const handleDelete = (cronJob: CronJob) => {
    setCronJobToDelete(cronJob)
    setShowDeleteModal(true)
  }

  const handleDeleteConfirm = () => {
    if (cronJobToDelete) {
      deleteMutation.mutate(cronJobToDelete.id)
    }
  }

  const formatDate = (dateString: string | null | undefined) => {
    if (!dateString) return 'Never'
    try {
      return new Date(dateString).toLocaleString()
    } catch {
      return 'Invalid date'
    }
  }

  const getStatusBadge = (status: CronJobStatus, currentRuns: number, maxRuns: number) => {
    if (status === CronJobStatus.COMPLETED || currentRuns >= maxRuns) {
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
          Completed
        </span>
      )
    }
    if (status === CronJobStatus.PAUSED) {
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
          Paused
        </span>
      )
    }
    return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
        Active
      </span>
    )
  }

  const toggleEvaluator = (evaluatorId: string) => {
    setFormData(prev => ({
      ...prev,
      evaluator_ids: prev.evaluator_ids.includes(evaluatorId)
        ? prev.evaluator_ids.filter(id => id !== evaluatorId)
        : [...prev.evaluator_ids, evaluatorId],
    }))
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Cron Jobs</h1>
          <p className="mt-1 text-sm text-gray-600">
            Schedule automated evaluator runs on a recurring schedule
          </p>
        </div>
        <Button onClick={() => setShowCreateModal(true)} className="flex items-center gap-2">
          <Plus className="w-4 h-4" />
          Create Cron Job
        </Button>
      </div>

      {/* Cron Jobs List */}
      <div className="bg-white shadow rounded-lg">
        {isLoading ? (
          <div className="px-6 py-8 text-center">
            <p className="text-gray-500">Loading cron jobs...</p>
          </div>
        ) : isError ? (
          <div className="px-6 py-12 text-center">
            <Clock className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-sm font-medium text-gray-900">Unable to load cron jobs</h3>
            <p className="mt-2 text-sm text-gray-500">
              There was an error loading cron jobs. Please try again later.
            </p>
            <div className="mt-6">
              <Button onClick={() => setShowCreateModal(true)}>
                <Plus className="w-4 h-4 mr-2" />
                Create Cron Job
              </Button>
            </div>
          </div>
        ) : cronJobs.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <Clock className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-sm font-medium text-gray-900">No cron jobs</h3>
            <p className="mt-2 text-sm text-gray-500">
              Create a cron job to schedule automated evaluator runs
            </p>
            <div className="mt-6">
              <Button onClick={() => setShowCreateModal(true)}>
                <Plus className="w-4 h-4 mr-2" />
                Create Cron Job
              </Button>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {cronJobs.map((cronJob: CronJob) => (
              <div key={cronJob.id} className="px-6 py-4 hover:bg-gray-50">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <Clock className="h-5 w-5 text-gray-400" />
                      <div>
                        <h3 className="text-sm font-medium text-gray-900">{cronJob.name}</h3>
                        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3.5 w-3.5" />
                            {cronJob.cron_expression}
                          </span>
                          <span className="flex items-center gap-1">
                            <Globe className="h-3.5 w-3.5" />
                            {cronJob.timezone}
                          </span>
                          <span>
                            Runs: {cronJob.current_runs} / {cronJob.max_runs}
                          </span>
                        </div>
                        <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                          <span>Last run: {formatDate(cronJob.last_run_at)}</span>
                          <span>Next run: {formatDate(cronJob.next_run_at)}</span>
                        </div>
                        <div className="mt-2 text-xs text-gray-500">
                          {cronJob.evaluator_ids?.length || 0} evaluator(s) attached
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 ml-4">
                    {getStatusBadge(cronJob.status, cronJob.current_runs, cronJob.max_runs)}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => toggleMutation.mutate(cronJob.id)}
                        className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
                        title={cronJob.status === CronJobStatus.ACTIVE ? 'Pause' : 'Resume'}
                        disabled={cronJob.current_runs >= cronJob.max_runs}
                      >
                        {cronJob.status === CronJobStatus.ACTIVE ? (
                          <Pause className="h-4 w-4" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        onClick={() => handleEdit(cronJob)}
                        className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
                        title="Edit"
                      >
                        <Edit className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(cronJob)}
                        className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            <div
              className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75"
              onClick={closeModal}
            />
            <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-2xl sm:w-full">
              <div className="bg-white px-6 py-5">
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-semibold text-gray-900">
                    {editingCronJob ? 'Edit Cron Job' : 'Create Cron Job'}
                  </h3>
                  <button
                    onClick={closeModal}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <div className="space-y-5">
                  {/* Name */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Name <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                      placeholder="e.g., Daily Evaluation Run"
                    />
                  </div>

                  {/* Cron Expression */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Schedule <span className="text-red-500">*</span>
                    </label>
                    <select
                      value={selectedPreset}
                      onChange={e => handlePresetChange(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent mb-2"
                    >
                      {CRON_PRESETS.map(preset => (
                        <option key={preset.value} value={preset.value}>
                          {preset.label} {preset.value !== 'custom' ? `(${preset.value})` : ''}
                        </option>
                      ))}
                    </select>
                    {selectedPreset === 'custom' && (
                      <div className="mt-2">
                        <input
                          type="text"
                          value={formData.cron_expression}
                          onChange={e => setFormData(prev => ({ ...prev, cron_expression: e.target.value }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                          placeholder="e.g., 0 9 * * 1-5"
                        />
                        <p className="mt-1 text-xs text-gray-500 flex items-center gap-1">
                          <Info className="h-3 w-3" />
                          Format: minute hour day-of-month month day-of-week
                        </p>
                      </div>
                    )}
                    {selectedPreset !== 'custom' && (
                      <p className="text-xs text-gray-500">
                        {CRON_PRESETS.find(p => p.value === selectedPreset)?.description}
                      </p>
                    )}
                  </div>

                  {/* Timezone */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Timezone <span className="text-red-500">*</span>
                    </label>
                    <select
                      value={formData.timezone}
                      onChange={e => setFormData(prev => ({ ...prev, timezone: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                    >
                      {TIMEZONES.map(tz => (
                        <option key={tz.value} value={tz.value}>
                          {tz.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Max Runs */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Number of Times to Run <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="1000"
                      value={formData.max_runs}
                      onChange={e => setFormData(prev => ({ ...prev, max_runs: parseInt(e.target.value) || 1 }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      The cron job will stop after running this many times
                    </p>
                  </div>

                  {/* Evaluators Selection */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Evaluators to Trigger <span className="text-red-500">*</span>
                    </label>
                    <div className="border border-gray-300 rounded-md max-h-48 overflow-y-auto">
                      {evaluators.length === 0 ? (
                        <div className="px-3 py-4 text-sm text-gray-500 text-center">
                          No evaluators available. Create evaluators first.
                        </div>
                      ) : (
                        <div className="divide-y divide-gray-200">
                          {evaluators.map((evaluator: Evaluator) => {
                            const evaluatorId = evaluator.id || evaluator.evaluator_id
                            const isSelected = formData.evaluator_ids.includes(evaluatorId)
                            return (
                              <label
                                key={evaluatorId}
                                className={`flex items-center px-3 py-2 cursor-pointer hover:bg-gray-50 ${
                                  isSelected ? 'bg-gray-50' : ''
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => toggleEvaluator(evaluatorId)}
                                  className="h-4 w-4 text-gray-900 border-gray-300 rounded focus:ring-gray-900"
                                />
                                <span className="ml-3 text-sm text-gray-700">
                                  {getEvaluatorDisplayName(evaluator)}
                                </span>
                              </label>
                            )
                          })}
                        </div>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {formData.evaluator_ids.length} evaluator(s) selected
                    </p>
                  </div>
                </div>

                <div className="mt-6 flex justify-end gap-3">
                  <Button variant="outline" onClick={closeModal}>
                    Cancel
                  </Button>
                  <Button
                    onClick={handleSubmit}
                    isLoading={createMutation.isPending || updateMutation.isPending}
                  >
                    {editingCronJob ? 'Update' : 'Create'}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteModal}
        title="Delete Cron Job"
        description={`Are you sure you want to delete the cron job "${cronJobToDelete?.name}"? This action cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={handleDeleteConfirm}
        onCancel={() => {
          setShowDeleteModal(false)
          setCronJobToDelete(null)
        }}
        isLoading={deleteMutation.isPending}
        variant="danger"
      />

      <ToastContainer />
    </div>
  )
}
