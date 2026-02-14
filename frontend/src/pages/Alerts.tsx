import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
import ConfirmModal from '../components/ConfirmModal'
import { Plus, Trash2, X, Bell, Mail, Globe, Zap, CheckCircle, AlertTriangle } from 'lucide-react'

// Types
interface Alert {
  id: string
  organization_id: string
  name: string
  description?: string
  metric_type: string
  aggregation: string
  operator: string
  threshold_value: number
  time_window_minutes: number
  agent_ids?: string[]
  notify_frequency: string
  notify_emails?: string[]
  notify_webhooks?: string[]
  status: string
  created_at: string
  updated_at: string
}

interface Agent {
  id: string
  name: string
  agent_id?: string
}

const METRIC_TYPES = [
  { value: 'number_of_calls', label: 'Number of Calls' },
  { value: 'call_duration', label: 'Call Duration' },
  { value: 'error_rate', label: 'Error Rate' },
  { value: 'success_rate', label: 'Success Rate' },
  { value: 'latency', label: 'Latency' },
  { value: 'custom', label: 'Custom' },
]

const AGGREGATIONS = [
  { value: 'sum', label: 'Sum' },
  { value: 'avg', label: 'Average' },
  { value: 'count', label: 'Count' },
  { value: 'min', label: 'Minimum' },
  { value: 'max', label: 'Maximum' },
]

const OPERATORS = [
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: '=', label: '=' },
  { value: '!=', label: '!=' },
]

const NOTIFY_FREQUENCIES = [
  { value: 'immediate', label: 'Immediate' },
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
]

export default function Alerts() {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [alertToDelete, setAlertToDelete] = useState<Alert | null>(null)
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    metric_type: 'number_of_calls',
    aggregation: 'sum',
    operator: '>',
    threshold_value: 100,
    time_window_minutes: 60,
    agent_ids: [] as string[],
    notify_frequency: 'immediate',
    notify_emails: [''],
    notify_webhooks: [''],
  })

  // Fetch alerts
  const { data: alerts = [], isLoading } = useQuery({
    queryKey: ['alerts'],
    queryFn: () => apiClient.listAlerts(),
  })

  // Fetch agents for selection
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const createMutation = useMutation({
    mutationFn: (data: any) => apiClient.createAlert(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      closeModal()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) =>
      apiClient.updateAlert(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      closeModal()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAlert(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      setShowDeleteModal(false)
      setAlertToDelete(null)
    },
  })

  const navigate = useNavigate()

  const [evaluatingAll, setEvaluatingAll] = useState(false)
  const [evaluateAllResult, setEvaluateAllResult] = useState<any | null>(null)

  const handleEvaluateAll = async () => {
    setEvaluatingAll(true)
    setEvaluateAllResult(null)
    try {
      const result = await apiClient.evaluateAllAlerts()
      setEvaluateAllResult(result)
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alertHistory'] })
    } catch {
      setEvaluateAllResult({ error: 'Failed to evaluate alerts' })
    } finally {
      setEvaluatingAll(false)
    }
  }

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      metric_type: 'number_of_calls',
      aggregation: 'sum',
      operator: '>',
      threshold_value: 100,
      time_window_minutes: 60,
      agent_ids: [],
      notify_frequency: 'immediate',
      notify_emails: [''],
      notify_webhooks: [''],
    })
  }

  const closeModal = () => {
    setShowCreateModal(false)
    setEditingAlert(null)
    resetForm()
  }

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      alert('Please enter an alert name')
      return
    }

    const payload = {
      name: formData.name,
      description: formData.description || null,
      metric_type: formData.metric_type,
      aggregation: formData.aggregation,
      operator: formData.operator,
      threshold_value: formData.threshold_value,
      time_window_minutes: formData.time_window_minutes,
      agent_ids: formData.agent_ids.length > 0 ? formData.agent_ids : null,
      notify_frequency: formData.notify_frequency,
      notify_emails: formData.notify_emails.filter(e => e.trim()),
      notify_webhooks: formData.notify_webhooks.filter(w => w.trim()),
    }

    if (editingAlert) {
      updateMutation.mutate({ id: editingAlert.id, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const handleDelete = (alertItem: Alert) => {
    setAlertToDelete(alertItem)
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    if (alertToDelete) {
      deleteMutation.mutate(alertToDelete.id)
    }
  }

  const closeDeleteModal = () => {
    setShowDeleteModal(false)
    setAlertToDelete(null)
  }

  const addEmail = () => {
    setFormData({ ...formData, notify_emails: [...formData.notify_emails, ''] })
  }

  const removeEmail = (index: number) => {
    const emails = formData.notify_emails.filter((_, i) => i !== index)
    setFormData({ ...formData, notify_emails: emails.length ? emails : [''] })
  }

  const updateEmail = (index: number, value: string) => {
    const emails = [...formData.notify_emails]
    emails[index] = value
    setFormData({ ...formData, notify_emails: emails })
  }

  const addWebhook = () => {
    setFormData({ ...formData, notify_webhooks: [...formData.notify_webhooks, ''] })
  }

  const removeWebhook = (index: number) => {
    const webhooks = formData.notify_webhooks.filter((_, i) => i !== index)
    setFormData({ ...formData, notify_webhooks: webhooks.length ? webhooks : [''] })
  }

  const updateWebhook = (index: number, value: string) => {
    const webhooks = [...formData.notify_webhooks]
    webhooks[index] = value
    setFormData({ ...formData, notify_webhooks: webhooks })
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return <span className="px-2 py-1 text-xs font-medium bg-emerald-100 text-emerald-800 rounded-full">Active</span>
      case 'paused':
        return <span className="px-2 py-1 text-xs font-medium bg-amber-100 text-amber-800 rounded-full">Paused</span>
      case 'disabled':
        return <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded-full">Disabled</span>
      default:
        return <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded-full">{status}</span>
    }
  }

  const formatCondition = (alertItem: Alert) => {
    const metric = METRIC_TYPES.find(m => m.value === alertItem.metric_type)?.label || alertItem.metric_type
    const agg = AGGREGATIONS.find(a => a.value === alertItem.aggregation)?.label || alertItem.aggregation
    return `${agg} of ${metric} ${alertItem.operator} ${alertItem.threshold_value}`
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Alerts</h1>
          <p className="mt-2 text-sm text-gray-600">
            Configure monitoring alerts for your voice AI agents
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            onClick={handleEvaluateAll}
            isLoading={evaluatingAll}
            leftIcon={<Zap className="w-4 h-4" />}
          >
            Evaluate All
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              resetForm()
              setEditingAlert(null)
              setShowCreateModal(true)
            }}
            leftIcon={<Plus className="w-4 h-4" />}
          >
            Create Alert
          </Button>
        </div>
      </div>

      {/* Evaluate All Result Banner */}
      {evaluateAllResult && (
        <div className={`rounded-lg p-4 flex items-center justify-between ${
          evaluateAllResult.error
            ? 'bg-red-50 border border-red-200'
            : evaluateAllResult.triggered > 0
              ? 'bg-amber-50 border border-amber-200'
              : 'bg-emerald-50 border border-emerald-200'
        }`}>
          <div className="flex items-center gap-3">
            {evaluateAllResult.error ? (
              <AlertTriangle className="w-5 h-5 text-red-500" />
            ) : evaluateAllResult.triggered > 0 ? (
              <AlertTriangle className="w-5 h-5 text-amber-500" />
            ) : (
              <CheckCircle className="w-5 h-5 text-emerald-500" />
            )}
            <div>
              {evaluateAllResult.error ? (
                <p className="text-sm font-medium text-red-800">{evaluateAllResult.error}</p>
              ) : (
                <p className="text-sm font-medium text-gray-800">
                  Evaluated {evaluateAllResult.total_alerts} alert{evaluateAllResult.total_alerts !== 1 ? 's' : ''}:
                  {' '}<span className="text-amber-700">{evaluateAllResult.triggered} triggered</span>,
                  {' '}<span className="text-emerald-700">{evaluateAllResult.not_triggered} ok</span>
                  {evaluateAllResult.skipped_cooldown > 0 && (
                    <>, <span className="text-gray-500">{evaluateAllResult.skipped_cooldown} cooldown</span></>
                  )}
                  {evaluateAllResult.errors > 0 && (
                    <>, <span className="text-red-600">{evaluateAllResult.errors} errors</span></>
                  )}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={() => setEvaluateAllResult(null)}
            className="p-1 text-gray-400 hover:text-gray-600 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Alerts Table */}
      <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Bell className="w-5 h-5 text-gray-500" />
            Alert Configurations
          </h2>
        </div>
        {isLoading ? (
          <div className="p-12 text-center text-gray-500">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto mb-4"></div>
            Loading alerts...
          </div>
        ) : alerts.length === 0 ? (
          <div className="p-12 text-center">
            <Bell className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500 mb-4">No alerts configured yet</p>
            <Button
              variant="primary"
              onClick={() => setShowCreateModal(true)}
              leftIcon={<Plus className="w-4 h-4" />}
            >
              Create Your First Alert
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Alert
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Condition
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Time Window
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Notifications
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {alerts.map((alertItem: Alert) => (
                  <tr
                    key={alertItem.id}
                    className="hover:bg-gray-50 transition-colors cursor-pointer"
                    onClick={() => navigate(`/alerts/${alertItem.id}`)}
                  >
                    <td className="px-6 py-4">
                      <div className="text-sm font-medium text-gray-900">{alertItem.name}</div>
                      {alertItem.description && (
                        <div className="text-sm text-gray-500 truncate max-w-xs">{alertItem.description}</div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-700 font-mono bg-gray-100 px-2 py-1 rounded">
                        {formatCondition(alertItem)}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-700">{alertItem.time_window_minutes} min</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {alertItem.notify_emails && alertItem.notify_emails.length > 0 && (
                          <span className="flex items-center gap-1 text-xs text-gray-600">
                            <Mail className="w-3 h-3" />
                            {alertItem.notify_emails.length}
                          </span>
                        )}
                        {alertItem.notify_webhooks && alertItem.notify_webhooks.length > 0 && (
                          <span className="flex items-center gap-1 text-xs text-gray-600">
                            <Globe className="w-3 h-3" />
                            {alertItem.notify_webhooks.length}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(alertItem.status)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(alertItem)}
                          leftIcon={<Trash2 className="w-4 h-4 text-red-500" />}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-900/60 backdrop-blur-sm transition-opacity"
              onClick={closeModal}
            />
            <div className="relative bg-white rounded-2xl shadow-2xl max-w-3xl w-full p-8 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-bold text-gray-900">
                  {editingAlert ? 'Edit Alert' : 'Create Alert'}
                </h2>
                <button
                  onClick={closeModal}
                  className="p-2 text-gray-400 hover:text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-6">
                {/* Basic Info */}
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Basic Information</h3>
                  <div className="grid grid-cols-1 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Alert Name *
                      </label>
                      <input
                        type="text"
                        value={formData.name}
                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                        placeholder="e.g., High Call Volume Alert"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Description
                      </label>
                      <textarea
                        value={formData.description}
                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        rows={2}
                        className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                        placeholder="Optional description..."
                      />
                    </div>
                  </div>
                </div>

                {/* Metric Condition */}
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Metric Condition</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Metric
                      </label>
                      <select
                        value={formData.metric_type}
                        onChange={(e) => setFormData({ ...formData, metric_type: e.target.value })}
                        className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                      >
                        {METRIC_TYPES.map(m => (
                          <option key={m.value} value={m.value}>{m.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Aggregation
                      </label>
                      <select
                        value={formData.aggregation}
                        onChange={(e) => setFormData({ ...formData, aggregation: e.target.value })}
                        className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                      >
                        {AGGREGATIONS.map(a => (
                          <option key={a.value} value={a.value}>{a.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Operator
                      </label>
                      <select
                        value={formData.operator}
                        onChange={(e) => setFormData({ ...formData, operator: e.target.value })}
                        className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                      >
                        {OPERATORS.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Threshold
                      </label>
                      <input
                        type="number"
                        value={formData.threshold_value}
                        onChange={(e) => setFormData({ ...formData, threshold_value: parseFloat(e.target.value) || 0 })}
                        className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Time Window (minutes)
                    </label>
                    <input
                      type="number"
                      value={formData.time_window_minutes}
                      onChange={(e) => setFormData({ ...formData, time_window_minutes: parseInt(e.target.value) || 60 })}
                      min={1}
                      className="w-full md:w-48 px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                    />
                  </div>
                </div>

                {/* Agent Selection */}
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Agent Selection</h3>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Apply to Agents
                    </label>
                    <div className="border border-gray-300 rounded-lg p-4 max-h-48 overflow-y-auto bg-gray-50">
                      <div className="flex items-center mb-3 pb-3 border-b border-gray-200">
                        <input
                          type="checkbox"
                          id="all-agents"
                          checked={formData.agent_ids.length === 0}
                          onChange={() => setFormData({ ...formData, agent_ids: [] })}
                          className="h-4 w-4 text-gray-900 focus:ring-gray-500 border-gray-300 rounded"
                        />
                        <label htmlFor="all-agents" className="ml-3 text-sm font-medium text-gray-900">
                          All Agents
                        </label>
                      </div>
                      {agents.map((agent: Agent) => (
                        <div key={agent.id} className="flex items-center py-2">
                          <input
                            type="checkbox"
                            id={`agent-${agent.id}`}
                            checked={formData.agent_ids.includes(agent.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setFormData({ ...formData, agent_ids: [...formData.agent_ids, agent.id] })
                              } else {
                                setFormData({ ...formData, agent_ids: formData.agent_ids.filter(id => id !== agent.id) })
                              }
                            }}
                            className="h-4 w-4 text-gray-900 focus:ring-gray-500 border-gray-300 rounded"
                          />
                          <label htmlFor={`agent-${agent.id}`} className="ml-3 text-sm text-gray-700">
                            {agent.name}
                            {agent.agent_id && <span className="ml-2 text-gray-400">({agent.agent_id})</span>}
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Notification Settings */}
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Notification Settings</h3>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Notification Frequency
                    </label>
                    <select
                      value={formData.notify_frequency}
                      onChange={(e) => setFormData({ ...formData, notify_frequency: e.target.value })}
                      className="w-full md:w-64 px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                    >
                      {NOTIFY_FREQUENCIES.map(f => (
                        <option key={f.value} value={f.value}>{f.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* Email Notifications */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      <Mail className="w-4 h-4 inline mr-2" />
                      Email Notifications
                    </label>
                    <div className="space-y-2">
                      {formData.notify_emails.map((email, index) => (
                        <div key={index} className="flex gap-2">
                          <input
                            type="email"
                            value={email}
                            onChange={(e) => updateEmail(index, e.target.value)}
                            placeholder="email@example.com"
                            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                          />
                          <button
                            type="button"
                            onClick={() => removeEmail(index)}
                            className="p-3 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                          >
                            <X className="w-5 h-5" />
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={addEmail}
                        className="text-sm text-gray-600 hover:text-gray-900 font-medium"
                      >
                        + Add another email
                      </button>
                    </div>
                  </div>

                  {/* Webhook Notifications */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      <Globe className="w-4 h-4 inline mr-2" />
                      Webhook Notifications (Slack, etc.)
                    </label>
                    <div className="space-y-2">
                      {formData.notify_webhooks.map((webhook, index) => (
                        <div key={index} className="flex gap-2">
                          <input
                            type="url"
                            value={webhook}
                            onChange={(e) => updateWebhook(index, e.target.value)}
                            placeholder="https://hooks.slack.com/services/..."
                            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                          />
                          <button
                            type="button"
                            onClick={() => removeWebhook(index)}
                            className="p-3 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                          >
                            <X className="w-5 h-5" />
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={addWebhook}
                        className="text-sm text-gray-600 hover:text-gray-900 font-medium"
                      >
                        + Add another webhook
                      </button>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-3 pt-6 border-t border-gray-200">
                  <Button variant="ghost" onClick={closeModal}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleSubmit}
                    isLoading={createMutation.isPending || updateMutation.isPending}
                  >
                    {editingAlert ? 'Update Alert' : 'Create Alert'}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteModal && alertToDelete !== null}
        title="Delete Alert"
        description={alertToDelete ? `Are you sure you want to delete "${alertToDelete.name}"? All associated alert history will also be deleted. This action cannot be undone.` : ''}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteMutation.isPending}
        onConfirm={confirmDelete}
        onCancel={closeDeleteModal}
      />
    </div>
  )
}
