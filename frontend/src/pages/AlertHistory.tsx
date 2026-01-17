import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
import { History, Bell, AlertTriangle, CheckCircle, Clock, Eye, X, Check, MessageSquare } from 'lucide-react'

// Types
interface Alert {
  id: string
  name: string
  description?: string
  metric_type: string
  aggregation: string
  operator: string
  threshold_value: number
}

interface AlertHistoryItem {
  id: string
  organization_id: string
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
  created_at: string
  updated_at: string
  alert?: Alert
}

const STATUS_FILTERS = [
  { value: '', label: 'All Status' },
  { value: 'triggered', label: 'Triggered' },
  { value: 'notified', label: 'Notified' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
]

export default function AlertHistory() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedItem, setSelectedItem] = useState<AlertHistoryItem | null>(null)
  const [showResolveModal, setShowResolveModal] = useState(false)
  const [resolutionNotes, setResolutionNotes] = useState('')

  // Fetch alert history
  const { data: historyItems = [], isLoading } = useQuery({
    queryKey: ['alertHistory', statusFilter],
    queryFn: () => apiClient.listAlertHistory(statusFilter || undefined),
  })

  const acknowledgeMutation = useMutation({
    mutationFn: (id: string) => apiClient.acknowledgeAlertHistory(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alertHistory'] })
      setSelectedItem(null)
    },
  })

  const resolveMutation = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes: string }) =>
      apiClient.resolveAlertHistory(id, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alertHistory'] })
      setSelectedItem(null)
      setShowResolveModal(false)
      setResolutionNotes('')
    },
  })

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'triggered':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-red-100 text-red-800 rounded-full">
            <AlertTriangle className="w-3 h-3" />
            Triggered
          </span>
        )
      case 'notified':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-amber-100 text-amber-800 rounded-full">
            <Bell className="w-3 h-3" />
            Notified
          </span>
        )
      case 'acknowledged':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded-full">
            <Eye className="w-3 h-3" />
            Acknowledged
          </span>
        )
      case 'resolved':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-emerald-100 text-emerald-800 rounded-full">
            <CheckCircle className="w-3 h-3" />
            Resolved
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded-full">
            {status}
          </span>
        )
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatRelativeTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMins / 60)
    const diffDays = Math.floor(diffHours / 24)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return formatDate(dateString)
  }

  const handleAcknowledge = (item: AlertHistoryItem) => {
    acknowledgeMutation.mutate(item.id)
  }

  const handleResolve = () => {
    if (selectedItem) {
      resolveMutation.mutate({ id: selectedItem.id, notes: resolutionNotes })
    }
  }

  const openResolveModal = (item: AlertHistoryItem) => {
    setSelectedItem(item)
    setShowResolveModal(true)
    setResolutionNotes('')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Alert History</h1>
          <p className="mt-2 text-sm text-gray-600">
            View and manage triggered alerts and their resolution status
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-gray-700">Status:</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent text-sm"
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* History Table */}
      <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <History className="w-5 h-5 text-gray-500" />
            Triggered Alerts
          </h2>
        </div>
        {isLoading ? (
          <div className="p-12 text-center text-gray-500">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto mb-4"></div>
            Loading alert history...
          </div>
        ) : historyItems.length === 0 ? (
          <div className="p-12 text-center">
            <History className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500 mb-2">No alert history found</p>
            <p className="text-sm text-gray-400">
              {statusFilter
                ? 'Try changing the status filter'
                : 'Triggered alerts will appear here'}
            </p>
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
                    Triggered
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Value / Threshold
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
                {historyItems.map((item: AlertHistoryItem) => (
                  <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="text-sm font-medium text-gray-900">
                        {item.alert?.name || 'Unknown Alert'}
                      </div>
                      {item.alert?.description && (
                        <div className="text-sm text-gray-500 truncate max-w-xs">
                          {item.alert.description}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm text-gray-700">
                        <Clock className="w-4 h-4 text-gray-400" />
                        <span title={formatDate(item.triggered_at)}>
                          {formatRelativeTime(item.triggered_at)}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm">
                        <span className="font-mono font-medium text-red-600">
                          {item.triggered_value.toLocaleString()}
                        </span>
                        <span className="text-gray-400 mx-1">/</span>
                        <span className="font-mono text-gray-500">
                          {item.threshold_value.toLocaleString()}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(item.status)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <div className="flex items-center justify-end gap-1">
                        {item.status === 'triggered' || item.status === 'notified' ? (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleAcknowledge(item)}
                              leftIcon={<Eye className="w-4 h-4" />}
                              isLoading={acknowledgeMutation.isPending}
                            >
                              Acknowledge
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openResolveModal(item)}
                              leftIcon={<Check className="w-4 h-4 text-emerald-600" />}
                            >
                              Resolve
                            </Button>
                          </>
                        ) : item.status === 'acknowledged' ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openResolveModal(item)}
                            leftIcon={<Check className="w-4 h-4 text-emerald-600" />}
                          >
                            Resolve
                          </Button>
                        ) : (
                          <span className="text-sm text-gray-400">
                            {item.resolved_by && (
                              <span title={`Resolved by ${item.resolved_by}`}>
                                Resolved
                              </span>
                            )}
                          </span>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setSelectedItem(item)}
                          leftIcon={<Eye className="w-4 h-4" />}
                        >
                          Details
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

      {/* Details Modal */}
      {selectedItem && !showResolveModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-900/60 backdrop-blur-sm transition-opacity"
              onClick={() => setSelectedItem(null)}
            />
            <div className="relative bg-white rounded-2xl shadow-2xl max-w-2xl w-full p-8 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-bold text-gray-900">Alert Details</h2>
                <button
                  onClick={() => setSelectedItem(null)}
                  className="p-2 text-gray-400 hover:text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-6">
                {/* Alert Info */}
                <div className="bg-gray-50 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                    Alert Information
                  </h3>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Name:</span>
                      <span className="font-medium">{selectedItem.alert?.name || 'Unknown'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Status:</span>
                      {getStatusBadge(selectedItem.status)}
                    </div>
                  </div>
                </div>

                {/* Trigger Details */}
                <div className="bg-gray-50 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                    Trigger Details
                  </h3>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Triggered At:</span>
                      <span className="font-medium">{formatDate(selectedItem.triggered_at)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Triggered Value:</span>
                      <span className="font-mono font-medium text-red-600">
                        {selectedItem.triggered_value.toLocaleString()}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Threshold:</span>
                      <span className="font-mono text-gray-700">
                        {selectedItem.threshold_value.toLocaleString()}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Timeline */}
                <div className="bg-gray-50 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
                    Timeline
                  </h3>
                  <div className="space-y-3">
                    <div className="flex items-start gap-3">
                      <div className="w-2 h-2 mt-2 rounded-full bg-red-500"></div>
                      <div>
                        <div className="font-medium text-gray-900">Triggered</div>
                        <div className="text-sm text-gray-500">{formatDate(selectedItem.triggered_at)}</div>
                      </div>
                    </div>
                    {selectedItem.notified_at && (
                      <div className="flex items-start gap-3">
                        <div className="w-2 h-2 mt-2 rounded-full bg-amber-500"></div>
                        <div>
                          <div className="font-medium text-gray-900">Notified</div>
                          <div className="text-sm text-gray-500">{formatDate(selectedItem.notified_at)}</div>
                        </div>
                      </div>
                    )}
                    {selectedItem.acknowledged_at && (
                      <div className="flex items-start gap-3">
                        <div className="w-2 h-2 mt-2 rounded-full bg-blue-500"></div>
                        <div>
                          <div className="font-medium text-gray-900">Acknowledged</div>
                          <div className="text-sm text-gray-500">
                            {formatDate(selectedItem.acknowledged_at)}
                            {selectedItem.acknowledged_by && ` by ${selectedItem.acknowledged_by}`}
                          </div>
                        </div>
                      </div>
                    )}
                    {selectedItem.resolved_at && (
                      <div className="flex items-start gap-3">
                        <div className="w-2 h-2 mt-2 rounded-full bg-emerald-500"></div>
                        <div>
                          <div className="font-medium text-gray-900">Resolved</div>
                          <div className="text-sm text-gray-500">
                            {formatDate(selectedItem.resolved_at)}
                            {selectedItem.resolved_by && ` by ${selectedItem.resolved_by}`}
                          </div>
                          {selectedItem.resolution_notes && (
                            <div className="mt-1 text-sm text-gray-600 bg-white rounded p-2 border border-gray-200">
                              {selectedItem.resolution_notes}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                  <Button variant="ghost" onClick={() => setSelectedItem(null)}>
                    Close
                  </Button>
                  {(selectedItem.status === 'triggered' || selectedItem.status === 'notified') && (
                    <Button
                      variant="secondary"
                      onClick={() => handleAcknowledge(selectedItem)}
                      leftIcon={<Eye className="w-4 h-4" />}
                      isLoading={acknowledgeMutation.isPending}
                    >
                      Acknowledge
                    </Button>
                  )}
                  {selectedItem.status !== 'resolved' && (
                    <Button
                      variant="primary"
                      onClick={() => {
                        setShowResolveModal(true)
                      }}
                      leftIcon={<Check className="w-4 h-4" />}
                    >
                      Resolve
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Resolve Modal */}
      {showResolveModal && selectedItem && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-900/60 backdrop-blur-sm transition-opacity"
              onClick={() => setShowResolveModal(false)}
            />
            <div className="relative bg-white rounded-2xl shadow-2xl max-w-lg w-full p-8">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-bold text-gray-900">Resolve Alert</h2>
                <button
                  onClick={() => setShowResolveModal(false)}
                  className="p-2 text-gray-400 hover:text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-500">Alert</div>
                  <div className="font-medium text-gray-900">{selectedItem.alert?.name}</div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <MessageSquare className="w-4 h-4 inline mr-2" />
                    Resolution Notes (optional)
                  </label>
                  <textarea
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                    rows={4}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                    placeholder="Describe how this alert was resolved..."
                  />
                </div>

                <div className="flex justify-end gap-3 pt-4">
                  <Button variant="ghost" onClick={() => setShowResolveModal(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleResolve}
                    leftIcon={<Check className="w-4 h-4" />}
                    isLoading={resolveMutation.isPending}
                  >
                    Mark as Resolved
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
