import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X, AlertCircle, Trash2 } from 'lucide-react'
import { format } from 'date-fns'
import Button from '../../../components/Button'
import { apiClient } from '../../../lib/api'
import { TestAgentConversation, TestAgent } from '../../../types/api'

interface DeleteAgentModalProps {
  isOpen: boolean
  agent: TestAgent | null
  blockingConversations: TestAgentConversation[]
  onClose: () => void
  onSuccess: () => void
  showToast: (message: string, type: 'success' | 'error') => void
  onGlobalAgentDeleted?: (agentId: string) => void
}

export default function DeleteAgentModal({
  isOpen,
  agent,
  blockingConversations,
  onClose,
  onSuccess,
  showToast,
  onGlobalAgentDeleted,
}: DeleteAgentModalProps) {
  const queryClient = useQueryClient()
  const [showConversationsList, setShowConversationsList] = useState(false)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)
  const [localBlockingConversations, setLocalBlockingConversations] = useState<TestAgentConversation[]>(blockingConversations)

  const deleteMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => apiClient.deleteAgent(id, force),
    onSuccess: (_, { id: deletedId }) => {
      onGlobalAgentDeleted?.(deletedId)
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      onSuccess()
      setShowConversationsList(false)
      setDeleteDependencies(null)
      showToast('Agent deleted successfully!', 'success')
    },
    onError: async (error: any) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail

      if (status === 409 && detail?.dependencies) {
        setDeleteDependencies(detail.dependencies)
        return
      }

      const errorMessage = typeof detail === 'string'
        ? detail
        : detail?.message || error.message || 'Failed to delete agent. Please try again.'

      showToast(errorMessage, 'error')
    },
  })

  const deleteConversationMutation = useMutation({
    mutationFn: (conversationId: string) => apiClient.deleteTestAgentConversation(conversationId),
    onSuccess: async (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['test-agent-conversations'] })
      const updated = localBlockingConversations.filter((c) => c.id !== deletedId)
      setLocalBlockingConversations(updated)
      if (updated.length === 0) {
        setShowConversationsList(false)
        showToast('All blocking conversations deleted. You can now delete the agent.', 'success')
      } else {
        showToast('Conversation deleted successfully!', 'success')
      }
    },
    onError: (error: any) => {
      showToast(`Failed to delete conversation: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const handleClose = () => {
    setShowConversationsList(false)
    setDeleteDependencies(null)
    onClose()
  }

  const confirmDelete = (force?: boolean) => {
    if (!agent) return
    deleteMutation.mutate({ id: agent.id, force })
  }

  if (!isOpen || !agent) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={handleClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="text-lg font-semibold text-gray-900">Delete Agent</h3>
          <button onClick={handleClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>
        
        <div className="p-6">
          {/* Dependencies Warning */}
          {deleteDependencies && (
            <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-amber-800 mb-2">
                    This agent has dependent records
                  </p>
                  <ul className="text-xs text-amber-700 space-y-1 mb-3">
                    {deleteDependencies.evaluators && (
                      <li>{deleteDependencies.evaluators} evaluator{deleteDependencies.evaluators !== 1 ? 's' : ''}</li>
                    )}
                    {deleteDependencies.evaluator_results && (
                      <li>{deleteDependencies.evaluator_results} evaluator result{deleteDependencies.evaluator_results !== 1 ? 's' : ''}</li>
                    )}
                    {deleteDependencies.call_recordings && (
                      <li>{deleteDependencies.call_recordings} call recording{deleteDependencies.call_recordings !== 1 ? 's' : ''} (will be unlinked, not deleted)</li>
                    )}
                    {deleteDependencies.conversation_evaluations && (
                      <li>{deleteDependencies.conversation_evaluations} conversation evaluation{deleteDependencies.conversation_evaluations !== 1 ? 's' : ''}</li>
                    )}
                    {deleteDependencies.test_conversations && (
                      <li>{deleteDependencies.test_conversations} test conversation{deleteDependencies.test_conversations !== 1 ? 's' : ''}</li>
                    )}
                  </ul>
                  <p className="text-xs text-amber-700">
                    You can force delete to remove this agent and all dependent records.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Blocking Conversations Warning */}
          {localBlockingConversations.length > 0 && !deleteDependencies && (
            <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-yellow-800 mb-2">
                    {localBlockingConversations.length} test conversation{localBlockingConversations.length !== 1 ? 's' : ''} found
                  </p>
                  <p className="text-xs text-yellow-700 mb-3">
                    This agent is being used by test conversations. You can delete them individually or use force delete.
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowConversationsList(!showConversationsList)}
                    className="text-xs"
                  >
                    {showConversationsList ? 'Hide' : 'Show'} Conversations ({localBlockingConversations.length})
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Conversations List */}
          {showConversationsList && localBlockingConversations.length > 0 && !deleteDependencies && (
            <div className="mb-6 border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
                <h4 className="text-sm font-medium text-gray-900">Test Conversations</h4>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {localBlockingConversations.map((conv) => (
                  <div key={conv.id} className="px-4 py-3 border-b border-gray-100 last:border-b-0 flex items-center justify-between">
                    <div className="flex-1">
                      <p className="text-sm text-gray-900">
                        Conversation {conv.id.substring(0, 8)}...
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        Status: <span className="capitalize">{conv.status}</span>
                        {conv.started_at && (
                          <> • Started: {format(new Date(conv.started_at), 'MMM d, yyyy HH:mm')}</>
                        )}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        if (confirm('Are you sure you want to delete this conversation?')) {
                          deleteConversationMutation.mutate(conv.id)
                        }
                      }}
                      isLoading={deleteConversationMutation.isPending}
                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                      leftIcon={<Trash2 className="h-3 w-3" />}
                    >
                      Delete
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Delete Confirmation */}
          <div className="flex items-start gap-4 mb-6">
            <div className="flex-shrink-0">
              <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                <Trash2 className="h-6 w-6 text-red-600" />
              </div>
            </div>
            <div className="flex-1">
              <p className="text-sm text-gray-700 mb-2">
                Are you sure you want to delete <span className="font-semibold text-gray-900">"{agent.name}"</span>?
              </p>
              <p className="text-xs text-gray-500">
                This action cannot be undone. The agent will be permanently deleted.
              </p>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <Button variant="outline" onClick={handleClose} className="flex-1">
              Cancel
            </Button>
            {deleteDependencies ? (
              <Button
                variant="danger"
                onClick={() => confirmDelete(true)}
                isLoading={deleteMutation.isPending}
                leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                className="flex-1"
              >
                Force Delete All
              </Button>
            ) : (
              <Button
                variant="danger"
                onClick={() => confirmDelete()}
                isLoading={deleteMutation.isPending}
                leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                className="flex-1"
              >
                Delete
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
