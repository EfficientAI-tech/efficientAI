import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState } from 'react'
import { APIKey } from '../types/api'
import { Key, Plus, Trash2, RotateCw, Copy, Check, AlertCircle } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

const MAX_API_KEYS = 5

export default function Settings() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showRegenerateModal, setShowRegenerateModal] = useState(false)
  const [showNewKeyModal, setShowNewKeyModal] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [keyToDelete, setKeyToDelete] = useState<APIKey | null>(null)
  const [keyToRegenerate, setKeyToRegenerate] = useState<APIKey | null>(null)
  const [newKey, setNewKey] = useState<string | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null)

  const { data: apiKeys = [], isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => apiClient.listApiKeys(),
  })

  const createMutation = useMutation({
    mutationFn: (name?: string) => apiClient.createApiKey(name),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setShowCreateModal(false)
      setNewKeyName('')
      setNewKey(data.key)
      setShowNewKeyModal(true)
      showToast('API key created successfully', 'success')
    },
    onError: (error: any) => {
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to create API key'
      showToast(errorMessage, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => apiClient.deleteApiKey(keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setShowDeleteModal(false)
      setKeyToDelete(null)
      showToast('API key deleted successfully', 'success')
    },
    onError: (error: any) => {
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to delete API key'
      showToast(errorMessage, 'error')
    },
  })

  const regenerateMutation = useMutation({
    mutationFn: (keyId: string) => apiClient.regenerateApiKey(keyId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setShowRegenerateModal(false)
      setKeyToRegenerate(null)
      setNewKey(data.key)
      setShowNewKeyModal(true)
      showToast('API key regenerated successfully', 'success')
    },
    onError: (error: any) => {
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to regenerate API key'
      showToast(errorMessage, 'error')
    },
  })

  const handleCreate = () => {
    if (apiKeys.length >= MAX_API_KEYS) {
      showToast(`Maximum of ${MAX_API_KEYS} API keys allowed. Please delete an existing key first.`, 'error')
      return
    }
    createMutation.mutate(newKeyName || undefined)
  }

  const handleDelete = (key: APIKey) => {
    setKeyToDelete(key)
    setShowDeleteModal(true)
  }

  const handleDeleteConfirm = () => {
    if (keyToDelete) {
      deleteMutation.mutate(keyToDelete.id)
    }
  }

  const handleRegenerate = (key: APIKey) => {
    setKeyToRegenerate(key)
    setShowRegenerateModal(true)
  }

  const handleRegenerateConfirm = () => {
    if (keyToRegenerate) {
      regenerateMutation.mutate(keyToRegenerate.id)
    }
  }

  const copyToClipboard = (text: string, keyId: string) => {
    navigator.clipboard.writeText(text)
    setCopiedKeyId(keyId)
    showToast('Copied to clipboard', 'success')
    setTimeout(() => setCopiedKeyId(null), 2000)
  }

  const formatDate = (dateString: string | null | undefined) => {
    if (!dateString) return 'Never'
    try {
      return new Date(dateString).toLocaleString()
    } catch {
      return 'Invalid date'
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
          <p className="mt-1 text-sm text-gray-600">
            Manage your API keys for authenticating API requests
          </p>
        </div>
        <Button
          onClick={() => setShowCreateModal(true)}
          disabled={apiKeys.length >= MAX_API_KEYS}
          className="flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          Create API Key
        </Button>
      </div>

      {apiKeys.length >= MAX_API_KEYS && (
        <div className="rounded-md bg-yellow-50 p-4 border border-yellow-200">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-yellow-400" />
            <div className="ml-3">
              <p className="text-sm text-yellow-800">
                You have reached the maximum of {MAX_API_KEYS} API keys. Delete an existing key to create a new one.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">API Keys</h2>
          <p className="mt-1 text-sm text-gray-600">
            API keys allow you to authenticate and make requests to the EfficientAI API
          </p>
        </div>

        {isLoading ? (
          <div className="px-6 py-8 text-center">
            <p className="text-gray-500">Loading API keys...</p>
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <Key className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-sm font-medium text-gray-900">No API keys</h3>
            <p className="mt-2 text-sm text-gray-500">
              Get started by creating your first API key
            </p>
            <div className="mt-6">
              <Button onClick={() => setShowCreateModal(true)}>
                <Plus className="w-4 h-4 mr-2" />
                Create API Key
              </Button>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {apiKeys.map((key: APIKey) => (
              <div key={key.id} className="px-6 py-4 hover:bg-gray-50">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <Key className="h-5 w-5 text-gray-400" />
                      <div>
                        <h3 className="text-sm font-medium text-gray-900">
                          {key.name || 'Unnamed Key'}
                        </h3>
                        <div className="mt-1 flex items-center gap-2">
                          <code className="text-xs font-mono text-gray-600 bg-gray-100 px-2 py-1 rounded">
                            {key.key}
                          </code>
                          <button
                            onClick={() => copyToClipboard(key.key, key.id)}
                            className="text-gray-400 hover:text-gray-600"
                            title="Copy masked key"
                          >
                            {copiedKeyId === key.id ? (
                              <Check className="h-4 w-4 text-green-600" />
                            ) : (
                              <Copy className="h-4 w-4" />
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                      <span>Created: {formatDate(key.created_at)}</span>
                      <span>Last used: {formatDate(key.last_used)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    <button
                      onClick={() => handleRegenerate(key)}
                      className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
                      title="Regenerate key"
                    >
                      <RotateCw className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(key)}
                      className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                      title="Delete key"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            <div className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75" onClick={() => setShowCreateModal(false)} />
            <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
              <div className="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
                <h3 className="text-lg font-medium text-gray-900 mb-4">Create API Key</h3>
                <div className="mb-4">
                  <label htmlFor="keyName" className="block text-sm font-medium text-gray-700">
                    Key Name (optional)
                  </label>
                  <input
                    type="text"
                    id="keyName"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
                    placeholder="e.g., Production Key, Development Key"
                  />
                </div>
                <div className="flex justify-end gap-3">
                  <Button variant="outline" onClick={() => setShowCreateModal(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleCreate} isLoading={createMutation.isPending}>
                    Create
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* New Key Modal */}
      {showNewKeyModal && newKey && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            <div className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75" onClick={() => {
              setShowNewKeyModal(false)
              setNewKey(null)
            }} />
            <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
              <div className="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
                <h3 className="text-lg font-medium text-gray-900 mb-2">API Key Created</h3>
                <p className="text-sm text-yellow-800 bg-yellow-50 border border-yellow-200 rounded p-3 mb-4">
                  ⚠️ Save this API key securely. You won't be able to see it again.
                </p>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Your API Key
                  </label>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 text-xs font-mono text-gray-900 bg-gray-100 px-3 py-2 rounded break-all">
                      {newKey}
                    </code>
                    <button
                      onClick={() => copyToClipboard(newKey, 'new')}
                      className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
                      title="Copy key"
                    >
                      {copiedKeyId === 'new' ? (
                        <Check className="h-4 w-4 text-green-600" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>
                <div className="flex justify-end">
                  <Button onClick={() => {
                    setShowNewKeyModal(false)
                    setNewKey(null)
                  }}>
                    I've Saved It
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      {showDeleteModal && keyToDelete && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            <div className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75" onClick={() => setShowDeleteModal(false)} />
            <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
              <div className="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
                <h3 className="text-lg font-medium text-gray-900 mb-4">Delete API Key</h3>
                <p className="text-sm text-gray-600 mb-4">
                  Are you sure you want to delete the API key <strong>{keyToDelete.name || 'Unnamed Key'}</strong>?
                  This action cannot be undone and any applications using this key will stop working.
                </p>
                <div className="flex justify-end gap-3">
                  <Button variant="outline" onClick={() => setShowDeleteModal(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="danger"
                    onClick={handleDeleteConfirm}
                    isLoading={deleteMutation.isPending}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Regenerate Modal */}
      {showRegenerateModal && keyToRegenerate && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            <div className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75" onClick={() => setShowRegenerateModal(false)} />
            <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
              <div className="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
                <h3 className="text-lg font-medium text-gray-900 mb-4">Regenerate API Key</h3>
                <p className="text-sm text-gray-600 mb-4">
                  Are you sure you want to regenerate the API key <strong>{keyToRegenerate.name || 'Unnamed Key'}</strong>?
                  The old key will be deactivated and a new key will be generated. Any applications using the old key will stop working.
                </p>
                <div className="flex justify-end gap-3">
                  <Button variant="outline" onClick={() => setShowRegenerateModal(false)}>
                    Cancel
                  </Button>
                  <Button
                    onClick={handleRegenerateConfirm}
                    isLoading={regenerateMutation.isPending}
                  >
                    Regenerate
                  </Button>
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

