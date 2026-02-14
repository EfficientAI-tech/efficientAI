import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'
import {
  ArrowLeft,
  Bell,
  Zap,
  Send,
  Play,
  Pause,
  Edit,
  Save,
  Trash2,
  Mail,
  Globe,
  Clock,
  Activity,
  AlertTriangle,
  CheckCircle,
  Eye,
  History,
  X,
  Plus,
} from 'lucide-react'

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

interface AlertHistoryItem {
  id: string
  alert_id: string
  triggered_at: string
  triggered_value: number
  threshold_value: number
  status: string
  notified_at?: string
  notification_details?: Record<string, any>
  acknowledged_at?: string
  acknowledged_by?: string
  resolved_at?: string
  resolved_by?: string
  resolution_notes?: string
  context_data?: Record<string, any>
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

const METRIC_LABELS: Record<string, string> = Object.fromEntries(METRIC_TYPES.map(m => [m.value, m.label]))
const AGGREGATION_LABELS: Record<string, string> = Object.fromEntries(AGGREGATIONS.map(a => [a.value, a.label]))
const FREQUENCY_LABELS: Record<string, string> = Object.fromEntries(NOTIFY_FREQUENCIES.map(f => [f.value, f.label]))

const inputClass = 'w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent'

export default function AlertDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [testLoading, setTestLoading] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
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

  // Fetch alert details
  const { data: alert, isLoading } = useQuery<Alert>({
    queryKey: ['alert', id],
    queryFn: () => apiClient.getAlert(id!),
    enabled: !!id,
  })

  // Fetch recent alert history for this alert
  const { data: historyItems = [] } = useQuery<AlertHistoryItem[]>({
    queryKey: ['alertHistory', id],
    queryFn: () => apiClient.listAlertHistory(undefined, id),
    enabled: !!id,
  })

  // Fetch agents for displaying names & selection
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  // Populate form when alert data loads
  useEffect(() => {
    if (alert) {
      setFormData({
        name: alert.name,
        description: alert.description || '',
        metric_type: alert.metric_type,
        aggregation: alert.aggregation,
        operator: alert.operator,
        threshold_value: alert.threshold_value,
        time_window_minutes: alert.time_window_minutes,
        agent_ids: alert.agent_ids || [],
        notify_frequency: alert.notify_frequency,
        notify_emails: alert.notify_emails?.length ? alert.notify_emails : [''],
        notify_webhooks: alert.notify_webhooks?.length ? alert.notify_webhooks : [''],
      })
    }
  }, [alert])

  // --- Mutations ---

  const updateMutation = useMutation({
    mutationFn: (data: any) => apiClient.updateAlert(id!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert', id] })
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      setIsEditMode(false)
      showToast('Alert updated successfully', 'success')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to update alert', 'error')
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (alertId: string) => apiClient.toggleAlertStatus(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert', id] })
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      showToast(
        alert?.status === 'active' ? 'Alert paused' : 'Alert resumed',
        'success'
      )
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to toggle alert', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (alertId: string) => apiClient.deleteAlert(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      showToast('Alert deleted', 'success')
      navigate('/alerts')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to delete alert', 'error')
    },
  })

  // --- Handlers ---

  const handleTrigger = async () => {
    if (!id) return
    setTriggerLoading(true)
    try {
      const result = await apiClient.triggerAlert(id)
      queryClient.invalidateQueries({ queryKey: ['alertHistory', id] })
      if (result.triggered) {
        showToast(
          `Alert triggered! Value: ${result.metric_value} (${result.notifications_successful || 0} notification${result.notifications_successful !== 1 ? 's' : ''} sent)`,
          'success'
        )
      } else {
        showToast(
          result.reason || 'Not triggered — current value does not breach threshold',
          'success'
        )
      }
    } catch (error: any) {
      showToast(error.response?.data?.detail || 'Failed to trigger alert', 'error')
    } finally {
      setTriggerLoading(false)
    }
  }

  const handleTestNotification = async () => {
    if (!id) return
    setTestLoading(true)
    try {
      const result = await apiClient.testAlertNotification(id, {})
      if (result.successful > 0) {
        showToast(
          `Test sent: ${result.successful}/${result.total} notification${result.total !== 1 ? 's' : ''} succeeded`,
          'success'
        )
      } else {
        showToast(
          result.detail || 'No notifications sent — configure emails or webhooks first',
          'error'
        )
      }
    } catch (error: any) {
      showToast(
        error.response?.data?.detail || 'Failed to send test notification',
        'error'
      )
    } finally {
      setTestLoading(false)
    }
  }

  const handleSave = () => {
    if (!formData.name.trim()) {
      showToast('Please enter an alert name', 'error')
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
    updateMutation.mutate(payload)
  }

  const handleCancelEdit = () => {
    if (alert) {
      setFormData({
        name: alert.name,
        description: alert.description || '',
        metric_type: alert.metric_type,
        aggregation: alert.aggregation,
        operator: alert.operator,
        threshold_value: alert.threshold_value,
        time_window_minutes: alert.time_window_minutes,
        agent_ids: alert.agent_ids || [],
        notify_frequency: alert.notify_frequency,
        notify_emails: alert.notify_emails?.length ? alert.notify_emails : [''],
        notify_webhooks: alert.notify_webhooks?.length ? alert.notify_webhooks : [''],
      })
    }
    setIsEditMode(false)
  }

  // --- Email / Webhook helpers ---

  const addEmail = () => setFormData({ ...formData, notify_emails: [...formData.notify_emails, ''] })
  const removeEmail = (index: number) => {
    const emails = formData.notify_emails.filter((_, i) => i !== index)
    setFormData({ ...formData, notify_emails: emails.length ? emails : [''] })
  }
  const updateEmail = (index: number, value: string) => {
    const emails = [...formData.notify_emails]
    emails[index] = value
    setFormData({ ...formData, notify_emails: emails })
  }

  const addWebhook = () => setFormData({ ...formData, notify_webhooks: [...formData.notify_webhooks, ''] })
  const removeWebhook = (index: number) => {
    const webhooks = formData.notify_webhooks.filter((_, i) => i !== index)
    setFormData({ ...formData, notify_webhooks: webhooks.length ? webhooks : [''] })
  }
  const updateWebhook = (index: number, value: string) => {
    const webhooks = [...formData.notify_webhooks]
    webhooks[index] = value
    setFormData({ ...formData, notify_webhooks: webhooks })
  }

  // --- Formatting helpers ---

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatRelativeTime = (dateString: string) => {
    const diffMs = Date.now() - new Date(dateString).getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMins / 60)
    const diffDays = Math.floor(diffHours / 24)
    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return formatDate(dateString)
  }

  const getAgentName = (agentId: string) => {
    const agent = agents.find((a: Agent) => a.id === agentId)
    return agent?.name || agentId.substring(0, 8) + '...'
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 text-sm font-medium bg-emerald-100 text-emerald-800 rounded-full">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            Active
          </span>
        )
      case 'paused':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 text-sm font-medium bg-amber-100 text-amber-800 rounded-full">
            <Pause className="w-3 h-3" />
            Paused
          </span>
        )
      case 'disabled':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 text-sm font-medium bg-gray-100 text-gray-600 rounded-full">
            Disabled
          </span>
        )
      default:
        return <span className="px-3 py-1 text-sm font-medium bg-gray-100 text-gray-600 rounded-full">{status}</span>
    }
  }

  const getHistoryStatusBadge = (status: string) => {
    switch (status) {
      case 'triggered':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 rounded-full">
            <AlertTriangle className="w-3 h-3" />Triggered
          </span>
        )
      case 'notified':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-800 rounded-full">
            <Bell className="w-3 h-3" />Notified
          </span>
        )
      case 'acknowledged':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 rounded-full">
            <Eye className="w-3 h-3" />Acknowledged
          </span>
        )
      case 'resolved':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-800 rounded-full">
            <CheckCircle className="w-3 h-3" />Resolved
          </span>
        )
      default:
        return <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">{status}</span>
    }
  }

  // --- Loading / Not found ---

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto mb-4" />
        <span className="text-gray-500 ml-3">Loading alert...</span>
      </div>
    )
  }

  if (!alert) {
    return (
      <div className="text-center py-12">
        <Bell className="w-12 h-12 text-gray-300 mx-auto mb-4" />
        <p className="text-gray-500 mb-4">Alert not found</p>
        <Button onClick={() => navigate('/alerts')} variant="outline" leftIcon={<ArrowLeft className="w-4 h-4" />}>
          Back to Alerts
        </Button>
      </div>
    )
  }

  // ====================================================================
  // RENDER
  // ====================================================================

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            onClick={() => navigate('/alerts')}
            variant="outline"
            leftIcon={<ArrowLeft className="w-4 h-4" />}
          >
            Back to Alerts
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-gray-900">
                {isEditMode ? 'Edit Alert' : alert.name}
              </h1>
              {!isEditMode && getStatusBadge(alert.status)}
            </div>
            {!isEditMode && alert.description && (
              <p className="text-sm text-gray-500 mt-1">{alert.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {!isEditMode ? (
            <>
              <Button
                variant="primary"
                onClick={handleTrigger}
                isLoading={triggerLoading}
                leftIcon={<Zap className="w-4 h-4" />}
              >
                Trigger
              </Button>
              <Button
                variant="outline"
                onClick={handleTestNotification}
                isLoading={testLoading}
                leftIcon={<Send className="w-4 h-4" />}
              >
                Test Notification
              </Button>
              <Button
                variant="outline"
                onClick={() => toggleMutation.mutate(alert.id)}
                isLoading={toggleMutation.isPending}
                leftIcon={alert.status === 'active' ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              >
                {alert.status === 'active' ? 'Pause' : 'Resume'}
              </Button>
              <Button
                variant="outline"
                onClick={() => setIsEditMode(true)}
                leftIcon={<Edit className="w-4 h-4" />}
              >
                Edit
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  if (confirm(`Are you sure you want to delete "${alert.name}"? This cannot be undone.`)) {
                    deleteMutation.mutate(alert.id)
                  }
                }}
                isLoading={deleteMutation.isPending}
                leftIcon={<Trash2 className="w-4 h-4" />}
              >
                Delete
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={handleCancelEdit}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleSave}
                isLoading={updateMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
              >
                Save Changes
              </Button>
            </>
          )}
        </div>
      </div>

      {/* ================================================================ */}
      {/* EDIT MODE                                                        */}
      {/* ================================================================ */}
      {isEditMode ? (
        <div className="bg-white shadow-sm rounded-xl border border-gray-200 p-8">
          <div className="space-y-8">
            {/* Basic Info */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider border-b border-gray-200 pb-2">
                Basic Information
              </h3>
              <div className="grid grid-cols-1 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Alert Name *</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className={inputClass}
                    placeholder="e.g., High Call Volume Alert"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={2}
                    className={inputClass}
                    placeholder="Optional description..."
                  />
                </div>
              </div>
            </div>

            {/* Metric Condition */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider border-b border-gray-200 pb-2">
                Metric Condition
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Metric</label>
                  <select
                    value={formData.metric_type}
                    onChange={(e) => setFormData({ ...formData, metric_type: e.target.value })}
                    className={inputClass}
                  >
                    {METRIC_TYPES.map(m => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Aggregation</label>
                  <select
                    value={formData.aggregation}
                    onChange={(e) => setFormData({ ...formData, aggregation: e.target.value })}
                    className={inputClass}
                  >
                    {AGGREGATIONS.map(a => (
                      <option key={a.value} value={a.value}>{a.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Operator</label>
                  <select
                    value={formData.operator}
                    onChange={(e) => setFormData({ ...formData, operator: e.target.value })}
                    className={inputClass}
                  >
                    {OPERATORS.map(o => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Threshold</label>
                  <input
                    type="number"
                    value={formData.threshold_value}
                    onChange={(e) => setFormData({ ...formData, threshold_value: parseFloat(e.target.value) || 0 })}
                    className={inputClass}
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Time Window (minutes)</label>
                <input
                  type="number"
                  value={formData.time_window_minutes}
                  onChange={(e) => setFormData({ ...formData, time_window_minutes: parseInt(e.target.value) || 60 })}
                  min={1}
                  className={`${inputClass} md:w-48`}
                />
              </div>
            </div>

            {/* Agent Selection */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider border-b border-gray-200 pb-2">
                Agent Selection
              </h3>
              <div className="border border-gray-300 rounded-lg p-4 max-h-48 overflow-y-auto bg-gray-50">
                <div className="flex items-center mb-3 pb-3 border-b border-gray-200">
                  <input
                    type="checkbox"
                    id="edit-all-agents"
                    checked={formData.agent_ids.length === 0}
                    onChange={() => setFormData({ ...formData, agent_ids: [] })}
                    className="h-4 w-4 text-gray-900 focus:ring-gray-500 border-gray-300 rounded"
                  />
                  <label htmlFor="edit-all-agents" className="ml-3 text-sm font-medium text-gray-900">
                    All Agents
                  </label>
                </div>
                {agents.map((agent: Agent) => (
                  <div key={agent.id} className="flex items-center py-2">
                    <input
                      type="checkbox"
                      id={`edit-agent-${agent.id}`}
                      checked={formData.agent_ids.includes(agent.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setFormData({ ...formData, agent_ids: [...formData.agent_ids, agent.id] })
                        } else {
                          setFormData({ ...formData, agent_ids: formData.agent_ids.filter(aid => aid !== agent.id) })
                        }
                      }}
                      className="h-4 w-4 text-gray-900 focus:ring-gray-500 border-gray-300 rounded"
                    />
                    <label htmlFor={`edit-agent-${agent.id}`} className="ml-3 text-sm text-gray-700">
                      {agent.name}
                      {agent.agent_id && <span className="ml-2 text-gray-400">({agent.agent_id})</span>}
                    </label>
                  </div>
                ))}
              </div>
            </div>

            {/* Notification Settings */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider border-b border-gray-200 pb-2">
                Notification Settings
              </h3>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Notification Frequency</label>
                <select
                  value={formData.notify_frequency}
                  onChange={(e) => setFormData({ ...formData, notify_frequency: e.target.value })}
                  className={`${inputClass} md:w-64`}
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
                        className={`flex-1 ${inputClass}`}
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
                    className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900 font-medium"
                  >
                    <Plus className="w-4 h-4" /> Add another email
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
                        className={`flex-1 ${inputClass}`}
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
                    className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900 font-medium"
                  >
                    <Plus className="w-4 h-4" /> Add another webhook
                  </button>
                </div>
              </div>
            </div>

            {/* Bottom save bar */}
            <div className="flex justify-between items-center pt-6 border-t border-gray-200">
              <Button
                variant="danger"
                onClick={() => {
                  if (confirm(`Are you sure you want to delete "${alert.name}"? This cannot be undone.`)) {
                    deleteMutation.mutate(alert.id)
                  }
                }}
                isLoading={deleteMutation.isPending}
                leftIcon={<Trash2 className="w-4 h-4" />}
              >
                Delete Alert
              </Button>
              <div className="flex gap-3">
                <Button variant="outline" onClick={handleCancelEdit}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={handleSave}
                  isLoading={updateMutation.isPending}
                  leftIcon={<Save className="w-4 h-4" />}
                >
                  Save Changes
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* ================================================================ */
        /* VIEW MODE                                                        */
        /* ================================================================ */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column — Alert Configuration */}
          <div className="lg:col-span-2 space-y-6">
            {/* Metric Condition */}
            <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Activity className="w-5 h-5 text-gray-500" />
                  Metric Condition
                </h2>
              </div>
              <div className="p-6">
                <div className="bg-gray-50 rounded-lg p-4 mb-6">
                  <p className="text-lg font-mono text-gray-900 text-center">
                    <span className="text-gray-600">{AGGREGATION_LABELS[alert.aggregation] || alert.aggregation}</span>
                    {' of '}
                    <span className="font-semibold text-gray-900">{METRIC_LABELS[alert.metric_type] || alert.metric_type}</span>
                    {' '}
                    <span className="text-red-600 font-bold">{alert.operator}</span>
                    {' '}
                    <span className="font-bold text-gray-900">{alert.threshold_value}</span>
                  </p>
                  <p className="text-sm text-gray-500 text-center mt-2">
                    over a <span className="font-medium">{alert.time_window_minutes} minute</span> window
                  </p>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Metric</dt>
                    <dd className="mt-1 text-sm font-medium text-gray-900">
                      {METRIC_LABELS[alert.metric_type] || alert.metric_type}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Aggregation</dt>
                    <dd className="mt-1 text-sm font-medium text-gray-900">
                      {AGGREGATION_LABELS[alert.aggregation] || alert.aggregation}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Operator</dt>
                    <dd className="mt-1 text-sm font-mono font-bold text-gray-900">{alert.operator}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Threshold</dt>
                    <dd className="mt-1 text-sm font-mono font-bold text-gray-900">{alert.threshold_value}</dd>
                  </div>
                </div>
              </div>
            </div>

            {/* Agent Scope */}
            <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Bell className="w-5 h-5 text-gray-500" />
                  Agent Scope
                </h2>
              </div>
              <div className="p-6">
                {alert.agent_ids && alert.agent_ids.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {alert.agent_ids.map((agentId) => (
                      <span
                        key={agentId}
                        className="inline-flex items-center px-3 py-1.5 bg-blue-50 text-blue-700 text-sm font-medium rounded-lg border border-blue-100"
                      >
                        {getAgentName(agentId)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-600 flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-emerald-500" />
                    Monitoring <span className="font-medium">all agents</span>
                  </p>
                )}
              </div>
            </div>

            {/* Recent Alert History */}
            <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <History className="w-5 h-5 text-gray-500" />
                  Recent Alert History
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => navigate('/alerts/history')}
                >
                  View All
                </Button>
              </div>
              {historyItems.length === 0 ? (
                <div className="p-8 text-center">
                  <History className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                  <p className="text-sm text-gray-500">No alert history yet</p>
                  <p className="text-xs text-gray-400 mt-1">
                    Triggered alerts will appear here
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-gray-100">
                  {historyItems.slice(0, 10).map((item) => (
                    <div key={item.id} className="px-6 py-3 flex items-center justify-between hover:bg-gray-50 transition-colors">
                      <div className="flex items-center gap-3">
                        {getHistoryStatusBadge(item.status)}
                        <div>
                          <p className="text-sm text-gray-700">
                            Value: <span className="font-mono font-medium text-red-600">{item.triggered_value}</span>
                            <span className="text-gray-400 mx-1">/</span>
                            <span className="font-mono text-gray-500">{item.threshold_value}</span>
                          </p>
                        </div>
                      </div>
                      <span className="text-xs text-gray-500" title={formatDate(item.triggered_at)}>
                        {formatRelativeTime(item.triggered_at)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right Column — Notification Config & Metadata */}
          <div className="space-y-6">
            {/* Notification Configuration */}
            <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Send className="w-5 h-5 text-gray-500" />
                  Notifications
                </h2>
              </div>
              <div className="p-6 space-y-5">
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Frequency</dt>
                  <dd className="text-sm font-medium text-gray-900">
                    {FREQUENCY_LABELS[alert.notify_frequency] || alert.notify_frequency}
                  </dd>
                </div>

                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1">
                    <Mail className="w-3.5 h-3.5" /> Email Recipients
                  </dt>
                  {alert.notify_emails && alert.notify_emails.length > 0 ? (
                    <div className="space-y-1.5">
                      {alert.notify_emails.map((email, i) => (
                        <dd key={i} className="text-sm text-gray-700 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100">
                          {email}
                        </dd>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400 italic">No email recipients configured</p>
                  )}
                </div>

                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1">
                    <Globe className="w-3.5 h-3.5" /> Webhooks
                  </dt>
                  {alert.notify_webhooks && alert.notify_webhooks.length > 0 ? (
                    <div className="space-y-1.5">
                      {alert.notify_webhooks.map((webhook, i) => (
                        <dd key={i} className="text-sm text-gray-700 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100 truncate" title={webhook}>
                          {webhook.length > 45 ? webhook.substring(0, 42) + '...' : webhook}
                        </dd>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400 italic">No webhooks configured</p>
                  )}
                </div>
              </div>
            </div>

            {/* Metadata */}
            <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Clock className="w-5 h-5 text-gray-500" />
                  Metadata
                </h2>
              </div>
              <div className="p-6 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Created</span>
                  <span className="text-gray-900 font-medium">{formatDate(alert.created_at)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Updated</span>
                  <span className="text-gray-900 font-medium">{formatDate(alert.updated_at)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Time Window</span>
                  <span className="text-gray-900 font-medium">{alert.time_window_minutes} min</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Total Triggers</span>
                  <span className="text-gray-900 font-medium">{historyItems.length}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <ToastContainer />
    </div>
  )
}
