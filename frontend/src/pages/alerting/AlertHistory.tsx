import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { History, Eye, X, Check, MessageSquare, Search, Clock } from 'lucide-react'
import AlertingPageShell from './AlertingPageShell'
import StatCard from './StatCard'
import { formatRelativeTime, getNotificationFailures, isOpenIncident } from './alertUiUtils'
import IncidentDetailPanel from './IncidentDetailPanel'
import { DeliverySummaryBadge, IncidentStatusBadge } from './IncidentTableCells'
import { mergeAlertHistoryItem } from './mergeAlertHistoryItem'
import { useToast } from '../../hooks/useToast'
import { getApiErrorMessage } from '../../lib/apiErrors'

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
  { value: '', label: 'All statuses' },
  { value: '__open__', label: 'Open incidents' },
  { value: 'triggered', label: 'Triggered' },
  { value: 'notified', label: 'Notified' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
]

export default function AlertHistory() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [statusFilter, setStatusFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedItem, setSelectedItem] = useState<AlertHistoryItem | null>(null)
  const [showResolveModal, setShowResolveModal] = useState(false)
  const [resolutionNotes, setResolutionNotes] = useState('')
  const [incidentRefreshingId, setIncidentRefreshingId] = useState<string | null>(null)

  // Fetch alert history
  const { data: historyItems = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['alertHistory', statusFilter],
    queryFn: () =>
      apiClient.listAlertHistory(
        statusFilter && statusFilter !== '__open__' ? statusFilter : undefined
      ),
  })

  const applyIncidentUpdate = (id: string, updated: AlertHistoryItem) => {
    setSelectedItem(prev => {
      if (!prev || prev.id !== id) return prev
      return mergeAlertHistoryItem(prev, updated)
    })
    queryClient.setQueriesData<AlertHistoryItem[]>(
      { queryKey: ['alertHistory'] },
      old => old?.map(h => (h.id === id ? mergeAlertHistoryItem(h, updated) : h))
    )
  }

  const refreshSelectedIncident = async (id: string, updated?: AlertHistoryItem) => {
    setIncidentRefreshingId(id)
    if (updated) {
      applyIncidentUpdate(id, updated)
    }
    try {
      const fresh = await apiClient.getAlertHistoryItem(id)
      if (fresh) {
        setSelectedItem(prev =>
          prev?.id === id && prev ? mergeAlertHistoryItem(prev, fresh) : fresh
        )
        queryClient.setQueriesData<AlertHistoryItem[]>(
          { queryKey: ['alertHistory'] },
          old => old?.map(h => (h.id === id ? mergeAlertHistoryItem(h, fresh) : h))
        )
      }
    } catch {
      showToast('Could not refresh incident details; showing last known state.', 'error')
    } finally {
      setIncidentRefreshingId(null)
      await queryClient.invalidateQueries({ queryKey: ['alertHistory'] })
    }
  }

  const acknowledgeMutation = useMutation({
    mutationFn: (id: string) => apiClient.acknowledgeAlertHistory(id),
    onSuccess: (data, id) => {
      void refreshSelectedIncident(id, data as AlertHistoryItem)
      showToast('Incident acknowledged', 'success')
    },
    onError: err =>
      showToast(getApiErrorMessage(err, 'Could not acknowledge incident'), 'error'),
  })

  const resolveMutation = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes: string }) =>
      apiClient.resolveAlertHistory(id, notes),
    onSuccess: (data, { id }) => {
      setShowResolveModal(false)
      setResolutionNotes('')
      void refreshSelectedIncident(id, data as AlertHistoryItem)
      showToast('Incident resolved', 'success')
    },
    onError: err =>
      showToast(getApiErrorMessage(err, 'Could not resolve incident'), 'error'),
  })

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

  const displayedItems = useMemo(() => {
    let list = historyItems as AlertHistoryItem[]
    if (statusFilter === '__open__') {
      list = list.filter(i => isOpenIncident(i.status))
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      list = list.filter(
        i =>
          (i.alert?.name || '').toLowerCase().includes(q) ||
          i.status.toLowerCase().includes(q)
      )
    }
    return list
  }, [historyItems, statusFilter, searchQuery])

  const openCount = useMemo(
    () => (historyItems as AlertHistoryItem[]).filter(i => isOpenIncident(i.status)).length,
    [historyItems]
  )
  const resolvedCount = useMemo(
    () => (historyItems as AlertHistoryItem[]).filter(i => i.status === 'resolved').length,
    [historyItems]
  )
  const notifyFailCount = useMemo(
    () =>
      (historyItems as AlertHistoryItem[]).filter(
        i => getNotificationFailures(i.notification_details).length > 0
      ).length,
    [historyItems]
  )

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
      <ToastContainer />
      <AlertingPageShell title="Alert history" />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <StatCard label="Open" value={openCount} tone={openCount > 0 ? 'warning' : 'default'} />
        <StatCard label="Resolved" value={resolvedCount} tone="success" />
        <StatCard label="Failed notify" value={notifyFailCount} tone={notifyFailCount > 0 ? 'danger' : 'default'} />
        <StatCard label="Shown" value={historyItems.length} />
      </div>

      <div className="flex flex-col sm:flex-row gap-3 sm:items-center bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-sm">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="search"
            placeholder="Search alerts…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border-0 bg-gray-50 rounded-lg focus:ring-2 focus:ring-gray-900/10"
          />
        </div>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white min-w-[160px]"
        >
          {STATUS_FILTERS.map(f => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </div>

      <div className="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
        {isError ? (
          <div className="p-12 text-center">
            <p className="text-red-600 text-sm mb-3">
              {getApiErrorMessage(error, 'Could not load alert history')}
            </p>
            <Button variant="secondary" onClick={() => refetch()}>Retry</Button>
          </div>
        ) : isLoading ? (
          <div className="p-12 text-center text-gray-500">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto mb-4"></div>
            Loading alert history...
          </div>
        ) : displayedItems.length === 0 ? (
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
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    Triggered
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    Value / Threshold
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {displayedItems.map((item: AlertHistoryItem) => {
                  const failures = getNotificationFailures(item.notification_details)
                  return (
                  <tr
                    key={item.id}
                    className={`hover:bg-gray-50 transition-colors ${
                      isOpenIncident(item.status) ? 'bg-amber-50/40' : ''
                    }`}
                  >
                    <td className="px-6 py-4">
                      <button
                        type="button"
                        className="text-sm font-medium text-gray-900 hover:text-gray-600 text-left"
                        onClick={() => navigate(`/alerts/${item.alert_id}`)}
                      >
                        {item.alert?.name || 'Unknown Alert'}
                      </button>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm text-gray-700">
                        <Clock className="w-4 h-4 text-gray-400 shrink-0" />
                        <span title={formatDate(item.triggered_at)}>
                          {formatRelativeTime(item.triggered_at)}
                        </span>
                      </div>
                      {failures.length > 0 && (
                        <span
                          className="text-xs text-red-600 mt-1 block"
                          title={failures.map(f => f.error).join('; ')}
                        >
                          Notify failed
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <span className="font-mono font-medium text-red-600">
                        {item.triggered_value.toLocaleString()}
                      </span>
                      <span className="text-gray-400 mx-1">/</span>
                      <span className="font-mono text-gray-500">
                        {item.threshold_value.toLocaleString()}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <IncidentStatusBadge status={item.status} />
                        <DeliverySummaryBadge notificationDetails={item.notification_details} />
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <div className="inline-flex items-center justify-end gap-1 flex-nowrap">
                        {item.status === 'triggered' || item.status === 'notified' ? (
                          <>
                            <Button
                              variant="ghost"
                              onClick={() => handleAcknowledge(item)}
                              leftIcon={<Eye className="w-4 h-4" />}
                              isLoading={acknowledgeMutation.isPending}
                            >
                              Acknowledge
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => openResolveModal(item)}
                              leftIcon={<Check className="w-4 h-4 text-emerald-600" />}
                            >
                              Resolve
                            </Button>
                          </>
                        ) : item.status === 'acknowledged' ? (
                          <Button
                            variant="ghost"
                            onClick={() => openResolveModal(item)}
                            leftIcon={<Check className="w-4 h-4 text-emerald-600" />}
                          >
                            Resolve
                          </Button>
                        ) : null}
                        <Button
                          variant="ghost"
                          onClick={() => setSelectedItem(item)}
                          leftIcon={<Eye className="w-4 h-4" />}
                        >
                          Details
                        </Button>
                      </div>
                    </td>
                  </tr>
                  )
                })}
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
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => setSelectedItem(null)}
            />
            <div className="relative bg-white rounded-2xl shadow-2xl max-w-3xl w-full p-8 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-gray-900">Incident</h2>
                <button
                  onClick={() => setSelectedItem(null)}
                  className="p-2 text-gray-400 hover:text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <IncidentDetailPanel
                item={selectedItem}
                statusBadge={<IncidentStatusBadge status={selectedItem.status} />}
                isRefreshing={incidentRefreshingId === selectedItem.id}
                actions={
                  <>
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
                        onClick={() => setShowResolveModal(true)}
                        leftIcon={<Check className="w-4 h-4" />}
                      >
                        Resolve
                      </Button>
                    )}
                  </>
                }
              />
            </div>
          </div>
        </div>
      )}

      {/* Resolve Modal */}
      {showResolveModal && selectedItem && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
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
