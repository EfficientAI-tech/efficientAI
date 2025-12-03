import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import Button from '../components/Button'
import { Plus, Edit, Trash2, X, ToggleLeft, ToggleRight } from 'lucide-react'

interface Metric {
  id: string
  name: string
  description?: string
  metric_type: 'number' | 'boolean' | 'rating'
  trigger: 'always'
  enabled: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

export default function MetricsManagement() {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingMetric, setEditingMetric] = useState<Metric | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    metric_type: 'rating' as 'number' | 'boolean' | 'rating',
    trigger: 'always' as 'always',
    enabled: true,
  })

  const { data: metrics = [], isLoading } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  // Seed default metrics on first load if none exist
  const seedMutation = useMutation({
    mutationFn: () => apiClient.seedDefaultMetrics(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  useEffect(() => {
    if (metrics.length === 0 && !isLoading) {
      seedMutation.mutate()
    }
  }, [metrics.length, isLoading])

  const createMutation = useMutation({
    mutationFn: (data: typeof formData) => apiClient.createMetric(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      setShowCreateModal(false)
      resetForm()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<typeof formData> }) =>
      apiClient.updateMetric(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      setEditingMetric(null)
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteMetric(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const toggleEnabledMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiClient.updateMetric(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      metric_type: 'rating',
      trigger: 'always',
      enabled: true,
    })
  }

  const handleCreate = () => {
    if (!formData.name.trim()) {
      alert('Please enter a metric name')
      return
    }
    createMutation.mutate(formData)
  }

  const handleEdit = (metric: Metric) => {
    setEditingMetric(metric)
    setFormData({
      name: metric.name,
      description: metric.description || '',
      metric_type: metric.metric_type,
      trigger: metric.trigger,
      enabled: metric.enabled,
    })
    setShowCreateModal(true)
  }

  const handleUpdate = () => {
    if (!editingMetric) return
    if (!formData.name.trim()) {
      alert('Please enter a metric name')
      return
    }
    updateMutation.mutate({ id: editingMetric.id, data: formData })
  }

  const handleToggleEnabled = (metric: Metric) => {
    toggleEnabledMutation.mutate({ id: metric.id, enabled: !metric.enabled })
  }

  const handleDelete = (metric: Metric) => {
    if (metric.is_default) {
      alert('Cannot delete default metrics')
      return
    }
    if (confirm(`Are you sure you want to delete "${metric.name}"?`)) {
      deleteMutation.mutate(metric.id)
    }
  }

  const closeModal = () => {
    setShowCreateModal(false)
    setEditingMetric(null)
    resetForm()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Metrics Management</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage evaluation metrics for your conversations
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            resetForm()
            setEditingMetric(null)
            setShowCreateModal(true)
          }}
          leftIcon={<Plus className="w-4 h-4" />}
        >
          Create Metric
        </Button>
      </div>

      {/* Metrics Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Metrics</h2>
        </div>
        {isLoading ? (
          <div className="p-6 text-center text-gray-500">Loading...</div>
        ) : metrics.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-4">No metrics yet. Default metrics will be created automatically.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Description
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Trigger
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Evaluation
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {metrics.map((metric: Metric) => (
                  <tr key={metric.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <div className="text-sm font-medium text-gray-900">{metric.name}</div>
                        {metric.is_default && (
                          <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded">
                            Default
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-500 max-w-md truncate">
                        {metric.description || '-'}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded capitalize">
                        {metric.metric_type}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded capitalize">
                        {metric.trigger}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <button
                        onClick={() => handleToggleEnabled(metric)}
                        className="flex items-center"
                        disabled={toggleEnabledMutation.isPending}
                      >
                        {metric.enabled ? (
                          <ToggleRight className="w-6 h-6 text-green-600" />
                        ) : (
                          <ToggleLeft className="w-6 h-6 text-gray-400" />
                        )}
                      </button>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex items-center justify-end space-x-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(metric)}
                          leftIcon={<Edit className="w-4 h-4" />}
                        >
                          Edit
                        </Button>
                        {!metric.is_default && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(metric)}
                            leftIcon={<Trash2 className="w-4 h-4" />}
                          >
                            Delete
                          </Button>
                        )}
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
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={closeModal}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">
                  {editingMetric ? 'Edit Metric' : 'Create Metric'}
                </h2>
                <button
                  onClick={closeModal}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Name *
                  </label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    disabled={editingMetric?.is_default}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-100"
                    placeholder="Enter metric name"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Description
                  </label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={3}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                    placeholder="Enter metric description"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Metric Type *
                  </label>
                  <select
                    value={formData.metric_type}
                    onChange={(e) => setFormData({ ...formData, metric_type: e.target.value as any })}
                    disabled={editingMetric?.is_default}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-100"
                  >
                    <option value="number">Number</option>
                    <option value="boolean">Boolean</option>
                    <option value="rating">Rating</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Trigger
                  </label>
                  <select
                    value={formData.trigger}
                    onChange={(e) => setFormData({ ...formData, trigger: e.target.value as any })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                  >
                    <option value="always">Always</option>
                  </select>
                </div>

                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="enabled"
                    checked={formData.enabled}
                    onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                    className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                  />
                  <label htmlFor="enabled" className="ml-2 block text-sm text-gray-900">
                    Enable this metric
                  </label>
                </div>

                <div className="flex justify-end space-x-3 pt-4">
                  <Button variant="ghost" onClick={closeModal}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={editingMetric ? handleUpdate : handleCreate}
                    isLoading={createMutation.isPending || updateMutation.isPending}
                  >
                    {editingMetric ? 'Update' : 'Create'}
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

