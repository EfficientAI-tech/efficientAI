import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Phone, Trash2, X, AlertCircle } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useAgentStore } from '../../store/agentStore'
import { useToast } from '../../hooks/useToast'
import { TestAgentConversation, TestAgent } from '../../types/api'
import { AgentsTable, CreateAgentModal, DeleteAgentModal } from './components'
import WalkthroughToggleButton from '../../components/walkthrough/WalkthroughToggleButton'

export default function Agents() {
  type BulkImpactItem = {
    id: string
    name: string
    dependencies: Record<string, number>
  }

  const queryClient = useQueryClient()
  const { selectedAgent: globalSelectedAgent, setSelectedAgent: setGlobalSelectedAgent } = useAgentStore()
  const { showToast, ToastContainer } = useToast()
  
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false)
  const [showBulkImpactModal, setShowBulkImpactModal] = useState(false)
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [isLoadingBulkImpact, setIsLoadingBulkImpact] = useState(false)
  const [forceBulkDelete, setForceBulkDelete] = useState(false)
  const [bulkImpactItems, setBulkImpactItems] = useState<BulkImpactItem[]>([])
  const [selectedAgent, setSelectedAgent] = useState<TestAgent | null>(null)
  const [blockingConversations, setBlockingConversations] = useState<TestAgentConversation[]>([])
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set())

  const { data: agents = [], isLoading: loading } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const handleSelectAgent = (agentId: string, checked: boolean) => {
    const newSelected = new Set(selectedAgents)
    if (checked) {
      newSelected.add(agentId)
    } else {
      newSelected.delete(agentId)
    }
    setSelectedAgents(newSelected)
  }

  const handleSelectAll = () => {
    if (selectedAgents.size === agents.length && agents.length > 0) {
      setSelectedAgents(new Set())
    } else {
      setSelectedAgents(new Set(agents.map((a: TestAgent) => a.id)))
    }
  }

  const openDeleteModalForAgent = async (agent: TestAgent) => {
    setSelectedAgent(agent)
    setShowDeleteModal(true)
    setBlockingConversations([])

    try {
      const conversations = await apiClient.listTestAgentConversations()
      const blocking = conversations.filter((conv: TestAgentConversation) => conv.agent_id === agent.id)
      if (blocking.length > 0) {
        setBlockingConversations(blocking)
      }
    } catch (err) {
      console.error('Error fetching conversations:', err)
    }
  }

  const handleCreateSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['agents'] })
    setShowCreateModal(false)
  }

  const handleDeleteSuccess = () => {
    setShowDeleteModal(false)
    setSelectedAgent(null)
    setBlockingConversations([])
    setSelectedAgents(new Set())
  }

  const executeBulkDelete = async (force: boolean) => {
    const selectedList = agents.filter((a: TestAgent) => selectedAgents.has(a.id))
    if (selectedList.length === 0) {
      showToast('No valid agents selected', 'error')
      return
    }

    setIsBulkDeleting(true)

    try {
      const results = await Promise.allSettled(
        selectedList.map((agent) => apiClient.deleteAgent(agent.id, force))
      )

      let successCount = 0
      const failedAgents: string[] = []
      const failedIds = new Set<string>()

      results.forEach((result, index) => {
        const agent = selectedList[index]
        if (result.status === 'fulfilled') {
          successCount += 1
          if (globalSelectedAgent?.id === agent.id) {
            setGlobalSelectedAgent(null)
          }
        } else {
          failedAgents.push(agent.name)
          failedIds.add(agent.id)
        }
      })

      if (successCount > 0) {
        queryClient.invalidateQueries({ queryKey: ['agents'] })
      }

      if (failedAgents.length === 0) {
        showToast(`Deleted ${successCount} agent${successCount !== 1 ? 's' : ''} successfully`, 'success')
        setSelectedAgents(new Set())
        setShowBulkDeleteModal(false)
        setShowBulkImpactModal(false)
        setBulkImpactItems([])
        setForceBulkDelete(false)
        return
      }

      if (successCount > 0) {
        showToast(
          `Deleted ${successCount}, but ${failedAgents.length} failed: ${failedAgents.join(', ')}`,
          'error'
        )
        setSelectedAgents(failedIds)
        setShowBulkDeleteModal(false)
        setShowBulkImpactModal(false)
        setBulkImpactItems([])
        setForceBulkDelete(false)
        return
      }

      showToast(
        `Failed to delete selected agents: ${failedAgents.join(', ')}`,
        'error'
      )
      setSelectedAgents(failedIds)
      setShowBulkDeleteModal(false)
      setShowBulkImpactModal(false)
      setBulkImpactItems([])
      setForceBulkDelete(false)
    } finally {
      setIsBulkDeleting(false)
    }
  }

  const handleReviewBulkImpact = async () => {
    const selectedList = agents.filter((a: TestAgent) => selectedAgents.has(a.id))
    if (selectedList.length === 0) {
      showToast('No valid agents selected', 'error')
      return
    }

    setIsLoadingBulkImpact(true)
    try {
      const results = await Promise.allSettled(
        selectedList.map((agent) => apiClient.getAgentDeleteImpact(agent.id))
      )

      const impactItems: BulkImpactItem[] = results.map((result, index) => {
        const fallbackAgent = selectedList[index]
        if (result.status === 'fulfilled') {
          return {
            id: fallbackAgent.id,
            name: result.value.agent_name || fallbackAgent.name,
            dependencies: result.value.dependencies || {},
          }
        }
        return {
          id: fallbackAgent.id,
          name: fallbackAgent.name,
          dependencies: {},
        }
      })

      setBulkImpactItems(impactItems)
      setShowBulkDeleteModal(false)
      setShowBulkImpactModal(true)
    } catch (err: any) {
      showToast(err?.response?.data?.detail || 'Failed to fetch dependency impact', 'error')
    } finally {
      setIsLoadingBulkImpact(false)
    }
  }

  const handleDeleteSelected = async () => {
    if (selectedAgents.size === 0) return

    const selectedIds = Array.from(selectedAgents)
    if (selectedIds.length === 1) {
      const agent = agents.find((a: TestAgent) => a.id === selectedIds[0])
      if (!agent) {
        showToast('Selected agent not found', 'error')
        return
      }
      await openDeleteModalForAgent(agent)
      return
    }

    setForceBulkDelete(false)
    setBulkImpactItems([])
    setShowBulkDeleteModal(true)
  }

  const handleGlobalAgentDeleted = (agentId: string) => {
    if (globalSelectedAgent?.id === agentId) {
      setGlobalSelectedAgent(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading agents...</div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">Test Agents</h1>
          <p className="text-gray-600 mt-1">Manage your voice AI test agents</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-2">
          {selectedAgents.size > 0 && (
            <Button
              variant="outline"
              onClick={handleDeleteSelected}
              leftIcon={<Trash2 className="w-4 h-4" />}
              className="border-red-300 text-red-700 hover:bg-red-50 hover:border-red-400"
            >
              Delete Selected
            </Button>
          )}
          <Button
            variant="primary"
            onClick={() => setShowCreateModal(true)}
            leftIcon={<Plus className="w-4 h-4" />}
          >
            Create Agent
          </Button>
          <WalkthroughToggleButton />
        </div>
      </div>

      {agents.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Phone className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No agents yet</h3>
          <p className="text-gray-500 mb-4">Create your first test agent to get started</p>
          <Button variant="ghost" onClick={() => setShowCreateModal(true)}>
            Create your first agent →
          </Button>
        </div>
      ) : (
        <AgentsTable
          agents={agents}
          integrations={integrations}
          selectedAgents={selectedAgents}
          onSelectAgent={handleSelectAgent}
          onSelectAll={handleSelectAll}
        />
      )}

      <CreateAgentModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSuccess={handleCreateSuccess}
        showToast={showToast}
      />

      <DeleteAgentModal
        isOpen={showDeleteModal}
        agent={selectedAgent}
        blockingConversations={blockingConversations}
        onClose={() => {
          setShowDeleteModal(false)
          setSelectedAgent(null)
          setBlockingConversations([])
        }}
        onSuccess={handleDeleteSuccess}
        showToast={showToast}
        onGlobalAgentDeleted={handleGlobalAgentDeleted}
      />

      {showBulkDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div
            className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete Selected Agents</h3>
              <button
                onClick={() => {
                  if (isBulkDeleting || isLoadingBulkImpact) return
                  setShowBulkDeleteModal(false)
                  setForceBulkDelete(false)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                <div className="flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-amber-800 mb-2">
                      Bulk delete operation
                    </p>
                    <p className="text-xs text-amber-700">
                      Force delete will remove dependent records for all selected agents. Review impact before confirming.
                    </p>
                  </div>
                </div>
              </div>

              <label className="flex items-start gap-2 mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <input
                  type="checkbox"
                  checked={forceBulkDelete}
                  onChange={(e) => setForceBulkDelete(e.target.checked)}
                  disabled={isBulkDeleting || isLoadingBulkImpact}
                  className="mt-0.5 rounded border-gray-300 text-red-600 focus:ring-red-500"
                />
                <span className="text-sm text-amber-900">
                  Force delete selected agents and dependent records.
                </span>
              </label>

              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0">
                  <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                    <Trash2 className="h-6 w-6 text-red-600" />
                  </div>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">
                    Are you sure you want to delete <span className="font-semibold text-gray-900">{selectedAgents.size}</span> selected agent{selectedAgents.size !== 1 ? 's' : ''}?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone.
                  </p>
                </div>
              </div>

              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowBulkDeleteModal(false)
                    setForceBulkDelete(false)
                  }}
                  disabled={isBulkDeleting || isLoadingBulkImpact}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={() => {
                    if (forceBulkDelete) {
                      void handleReviewBulkImpact()
                      return
                    }
                    void executeBulkDelete(false)
                  }}
                  disabled={!forceBulkDelete || isBulkDeleting || isLoadingBulkImpact}
                  isLoading={isBulkDeleting || isLoadingBulkImpact}
                  leftIcon={!(isBulkDeleting || isLoadingBulkImpact) ? <Trash2 className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Review Impact
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showBulkImpactModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div
            className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Force Delete Impact</h3>
              <button
                onClick={() => {
                  if (isBulkDeleting) return
                  setShowBulkImpactModal(false)
                  setBulkImpactItems([])
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                <div className="flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-amber-800 mb-2">
                      These dependent records will be affected
                    </p>
                    <p className="text-xs text-amber-700">
                      Force delete removes agents and dependent records. Call recordings are unlinked, not deleted.
                    </p>
                  </div>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                {bulkImpactItems.map((item) => {
                  const entries = Object.entries(item.dependencies)
                  return (
                    <div key={item.id} className="border border-gray-200 rounded-lg p-3">
                      <p className="text-sm font-medium text-gray-900 mb-2">{item.name}</p>
                      {entries.length > 0 ? (
                        <ul className="text-xs text-gray-700 space-y-1">
                          {entries.map(([key, count]) => (
                            <li key={key}>
                              {count} {key.replace(/_/g, ' ')}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-xs text-gray-500">No dependent records found.</p>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowBulkImpactModal(false)
                    setBulkImpactItems([])
                  }}
                  disabled={isBulkDeleting}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={() => {
                    void executeBulkDelete(true)
                  }}
                  isLoading={isBulkDeleting}
                  leftIcon={!isBulkDeleting ? <Trash2 className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Force Delete All
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      <ToastContainer />
    </div>
  )
}
