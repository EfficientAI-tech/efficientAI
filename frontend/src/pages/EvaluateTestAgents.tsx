import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useAgentStore } from '../store/agentStore'
import Button from '../components/Button'
import { Plus, Edit, Trash2, Play, X, CheckSquare, Square, Phone, Globe, Eye, AlertCircle } from 'lucide-react'
import { useToast } from '../hooks/useToast'

const DEFAULT_PERSONA_NAMES = [
  "Grumpy Old Man",
  "Confused Senior",
  "Busy Professional",
  "Friendly Customer",
  "Angry Caller"
]

const DEFAULT_SCENARIO_NAMES = [
  "Cancel Subscription",
  "Check Balance",
  "Technical Support",
  "Make Complaint",
  "Product Inquiry"
]

interface Evaluator {
  id: string
  evaluator_id: string
  agent_id: string
  persona_id: string
  scenario_id: string
  tags?: string[]
  created_at: string
  updated_at: string
}

export default function EvaluateTestAgents() {
  const { selectedAgent } = useAgentStore()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [selectedScenario, setSelectedScenario] = useState<string>('')
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [editTagInput, setEditTagInput] = useState('')
  const [editingEvaluator, setEditingEvaluator] = useState<Evaluator | null>(null)
  const [runningEvaluatorIds, setRunningEvaluatorIds] = useState<Set<string>>(new Set())
  const [selectedEvaluatorIds, setSelectedEvaluatorIds] = useState<Set<string>>(new Set())
  const [showRunModal, setShowRunModal] = useState(false)
  const [runCount, setRunCount] = useState(1)
  const [viewingEvaluator, setViewingEvaluator] = useState<Evaluator | null>(null)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [evaluatorToDelete, setEvaluatorToDelete] = useState<Evaluator | null>(null)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)

  const { data: personas = [] } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  const { data: evaluators = [], isLoading: loadingEvaluators } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
  })

  const filteredPersonas = personas.filter((p: any) => !DEFAULT_PERSONA_NAMES.includes(p.name))
  const filteredScenarios = scenarios.filter((s: any) => !DEFAULT_SCENARIO_NAMES.includes(s.name))

  // Fetch details for viewing evaluator
  const { data: evaluatorDetails, isLoading: loadingDetails } = useQuery({
    queryKey: ['evaluator-details', viewingEvaluator?.id],
    queryFn: async () => {
      if (!viewingEvaluator) return null
      const [agent, persona, scenario] = await Promise.all([
        apiClient.getAgent(viewingEvaluator.agent_id),
        apiClient.getPersona(viewingEvaluator.persona_id),
        apiClient.getScenario(viewingEvaluator.scenario_id),
      ])
      return { agent, persona, scenario }
    },
    enabled: !!viewingEvaluator,
  })

  const createMutation = useMutation({
    mutationFn: (data: { agent_id: string; scenario_id: string; persona_ids: string[]; tags?: string[] }) =>
      apiClient.createEvaluatorsBulk(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      setShowCreateModal(false)
      setSelectedScenario('')
      setSelectedPersonas([])
      setSelectedTags([])
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => apiClient.updateEvaluator(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      queryClient.invalidateQueries({ queryKey: ['evaluator-details'] })
      setEditingEvaluator(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => apiClient.deleteEvaluator(id, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      setShowDeleteModal(false)
      setEvaluatorToDelete(null)
      setDeleteDependencies(null)
      showToast('Evaluator deleted successfully!', 'success')
    },
    onError: (error: any) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail

      if (status === 409 && detail?.dependencies) {
        setDeleteDependencies(detail.dependencies)
        return
      }

      const errorMessage = typeof detail === 'string'
        ? detail
        : detail?.message || error.message || 'Failed to delete evaluator.'
      showToast(errorMessage, 'error')
    },
  })

  const handleCreate = () => {
    if (!selectedAgent) {
      alert('Please select an agent first')
      return
    }
    if (!selectedScenario) {
      alert('Please select a scenario')
      return
    }
    if (selectedPersonas.length === 0) {
      alert('Please select at least one persona')
      return
    }

    createMutation.mutate({
      agent_id: selectedAgent.id,
      scenario_id: selectedScenario,
      persona_ids: selectedPersonas,
      tags: selectedTags.length > 0 ? selectedTags : undefined,
    })
  }

  const togglePersona = (personaId: string) => {
    if (selectedPersonas.includes(personaId)) {
      setSelectedPersonas(selectedPersonas.filter(id => id !== personaId))
    } else {
      setSelectedPersonas([...selectedPersonas, personaId])
    }
  }

  const addTag = (tags: string[], setTags: (tags: string[]) => void, input: string, setInput: (input: string) => void) => {
    if (input.trim() && !tags.includes(input.trim())) {
      setTags([...tags, input.trim()])
      setInput('')
    }
  }

  const removeTag = (tag: string) => {
    setSelectedTags(selectedTags.filter(t => t !== tag))
  }

  const toggleEvaluatorSelection = (evaluatorId: string) => {
    setSelectedEvaluatorIds(prev => {
      const newSet = new Set(prev)
      if (newSet.has(evaluatorId)) {
        newSet.delete(evaluatorId)
      } else {
        newSet.add(evaluatorId)
      }
      return newSet
    })
  }

  const handleRunSelected = () => {
    if (selectedEvaluatorIds.size === 0) {
      showToast('Please select at least one evaluator to run', 'error')
      return
    }
    // Show the run modal to select how many times to run
    setRunCount(1)
    setShowRunModal(true)
  }

  const executeRuns = async () => {
    try {
      const evaluatorIdsArray = Array.from(selectedEvaluatorIds)
      setRunningEvaluatorIds(new Set(evaluatorIdsArray))
      setShowRunModal(false)
      
      // Create an array with each evaluator ID repeated runCount times
      const expandedIds: string[] = []
      for (const id of evaluatorIdsArray) {
        for (let i = 0; i < runCount; i++) {
          expandedIds.push(id)
        }
      }
      
      await apiClient.runEvaluators(expandedIds)
      
      // Invalidate queries to refresh results
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      
      // Clear selection after starting
      setSelectedEvaluatorIds(new Set())
      
      // Show success toast
      const totalRuns = evaluatorIdsArray.length * runCount
      showToast(`🚀 Queued ${totalRuns} evaluation${totalRuns > 1 ? 's' : ''}! Check Results for progress.`, 'success')
    } catch (error: any) {
      console.error('Failed to run evaluators:', error)
      showToast(`Failed to run evaluators: ${error?.response?.data?.detail || error?.message || 'Unknown error'}`, 'error')
      setRunningEvaluatorIds(new Set())
    }
  }

  const handleEdit = (evaluator: Evaluator) => {
    setEditingEvaluator(evaluator)
  }

  const handleSaveEdit = () => {
    if (!editingEvaluator) return
    updateMutation.mutate({
      id: editingEvaluator.id,
      data: {
        tags: editingEvaluator.tags || [],
      },
    })
  }

  return (
    <>
      <ToastContainer />
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Evaluator</h1>
            <p className="mt-2 text-sm text-gray-600">
              Manage evaluator configurations for testing agents with personas and scenarios
            </p>
          </div>
        <div className="flex items-center gap-3">
          <Button
            variant="success"
            onClick={handleRunSelected}
            disabled={selectedEvaluatorIds.size === 0 || runningEvaluatorIds.size > 0}
            leftIcon={<Play className="w-5 h-5" />}
            className="!px-6 !py-3 !text-base font-semibold shadow-lg hover:shadow-xl transition-shadow"
          >
            Run {selectedEvaluatorIds.size > 0 && `(${selectedEvaluatorIds.size})`}
          </Button>
          <Button
            variant="primary"
            onClick={() => setShowCreateModal(true)}
            leftIcon={<Plus className="w-4 h-4" />}
          >
            Create Evaluator
          </Button>
        </div>
      </div>

      {!selectedAgent && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800">
            Please select an agent from the top bar to create evaluators.
          </p>
        </div>
      )}

      {/* Evaluators List - Table Format */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Evaluators</h2>
          {evaluators.length > 0 && selectedEvaluatorIds.size > 0 && (
            <div className="text-sm text-gray-600">
              {selectedEvaluatorIds.size} selected
            </div>
          )}
        </div>
        {loadingEvaluators ? (
          <div className="p-6 text-center text-gray-500">Loading...</div>
        ) : evaluators.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-4">No evaluators yet. Create your first evaluator to get started.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
                    <span className="sr-only">Select</span>
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Persona
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider min-w-[300px]">
                    Scenario
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Tags
                  </th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {evaluators.map((evaluator: Evaluator) => {
                  const persona = personas.find((p: any) => p.id === evaluator.persona_id)
                  const scenario = scenarios.find((s: any) => s.id === evaluator.scenario_id)
                  const isRunning = runningEvaluatorIds.has(evaluator.id)
                  const isSelected = selectedEvaluatorIds.has(evaluator.id)

                  return (
                    <tr 
                      key={evaluator.id} 
                      className={`hover:bg-gray-50 transition-colors ${isSelected ? 'bg-blue-50' : ''}`}
                    >
                      {/* Checkbox */}
                      <td className="px-4 py-4 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => toggleEvaluatorSelection(evaluator.id)}
                          className="flex-shrink-0"
                          disabled={isRunning}
                        >
                          {isSelected ? (
                            <CheckSquare className="w-5 h-5 text-primary-600" />
                          ) : (
                            <Square className="w-5 h-5 text-gray-400" />
                          )}
                        </button>
                      </td>

                      {/* Evaluator ID */}
                      <td className="px-4 py-4 whitespace-nowrap">
                        <button
                          onClick={() => setViewingEvaluator(evaluator)}
                          className="font-mono font-semibold text-primary-600 hover:text-primary-800 hover:underline cursor-pointer"
                        >
                          {evaluator.evaluator_id}
                        </button>
                        {isRunning && (
                          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                            Running...
                          </span>
                        )}
                      </td>

                      {/* Persona */}
                      <td className="px-4 py-4 whitespace-nowrap">
                        <div className="flex flex-col">
                          <span className="text-sm font-medium text-gray-900">
                            {persona?.name || 'Unknown'}
                          </span>
                          {persona && (
                            <span className="text-xs text-gray-500">
                              {persona.language} • {persona.accent} • {persona.gender}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Scenario - Plain Text */}
                      <td className="px-4 py-4">
                        <div className="max-w-md">
                          <span className="text-sm font-medium text-gray-900">
                            {scenario?.name || 'Unknown Scenario'}
                          </span>
                          {scenario?.description && (
                            <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                              {scenario.description}
                            </p>
                          )}
                        </div>
                      </td>

                      {/* Tags */}
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap gap-1">
                          {evaluator.tags && evaluator.tags.length > 0 ? (
                            <>
                              {evaluator.tags.slice(0, 2).map((tag, idx) => (
                                <span
                                  key={idx}
                                  className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded"
                                >
                                  {tag}
                                </span>
                              ))}
                              {evaluator.tags.length > 2 && (
                                <span className="px-2 py-0.5 text-xs text-gray-500">
                                  +{evaluator.tags.length - 2}
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-4 whitespace-nowrap text-right">
                        <div className="flex items-center justify-end space-x-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEdit(evaluator)}
                            leftIcon={<Edit className="w-4 h-4" />}
                          >
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setEvaluatorToDelete(evaluator)
                              setDeleteDependencies(null)
                              setShowDeleteModal(true)
                            }}
                            leftIcon={<Trash2 className="w-4 h-4" />}
                          >
                            Delete
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

      {/* View Evaluator Details Modal */}
      {viewingEvaluator && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => setViewingEvaluator(null)}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-primary-100 rounded-lg">
                    <Eye className="w-5 h-5 text-primary-600" />
                  </div>
                  <div>
                    <h2 className="text-xl font-semibold text-gray-900">Evaluator Details</h2>
                    <p className="text-sm text-gray-500 font-mono">{viewingEvaluator.evaluator_id}</p>
                  </div>
                </div>
                <button
                  onClick={() => setViewingEvaluator(null)}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {loadingDetails ? (
                <div className="py-12 text-center text-gray-500">Loading details...</div>
              ) : evaluatorDetails ? (
                <div className="space-y-6">
                  {/* Agent Section */}
                  <div className="bg-gray-50 rounded-lg p-4">
                    <h3 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">Agent</h3>
                    <div className="space-y-2">
                      <p className="text-base font-medium text-gray-900">{evaluatorDetails.agent.name}</p>
                      {evaluatorDetails.agent.description && (
                        <p className="text-sm text-gray-600">{evaluatorDetails.agent.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-2">
                        {evaluatorDetails.agent.call_medium === 'web_call' ? (
                          <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-300">
                            <Globe className="w-3.5 h-3.5 mr-1.5" />
                            Web Call
                          </span>
                        ) : evaluatorDetails.agent.phone_number ? (
                          <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-teal-100 text-teal-800 border border-teal-300">
                            <Phone className="w-3.5 h-3.5 mr-1.5" />
                            {evaluatorDetails.agent.phone_number}
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-300">
                            No phone number
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Persona Section */}
                  <div className="bg-purple-50 rounded-lg p-4">
                    <h3 className="text-sm font-semibold text-purple-700 mb-3 uppercase tracking-wide">Persona</h3>
                    <div className="space-y-2">
                      <p className="text-base font-medium text-gray-900">{evaluatorDetails.persona.name}</p>
                      <div className="flex flex-wrap gap-2 mt-2">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white text-purple-800 border border-purple-200">
                          Language: {evaluatorDetails.persona.language}
                        </span>
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white text-purple-800 border border-purple-200">
                          Accent: {evaluatorDetails.persona.accent}
                        </span>
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white text-purple-800 border border-purple-200">
                          Gender: {evaluatorDetails.persona.gender}
                        </span>
                        {evaluatorDetails.persona.background_noise && (
                          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white text-purple-800 border border-purple-200">
                            Noise: {evaluatorDetails.persona.background_noise}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Scenario Section */}
                  <div className="bg-blue-50 rounded-lg p-4">
                    <h3 className="text-sm font-semibold text-blue-700 mb-3 uppercase tracking-wide">Scenario</h3>
                    <div className="space-y-2">
                      <p className="text-base font-medium text-gray-900">{evaluatorDetails.scenario.name}</p>
                      {evaluatorDetails.scenario.description && (
                        <p className="text-sm text-gray-600 mt-2">{evaluatorDetails.scenario.description}</p>
                      )}
                      {evaluatorDetails.scenario.required_info && Object.keys(evaluatorDetails.scenario.required_info).length > 0 && (
                        <div className="mt-3">
                          <p className="text-xs font-medium text-blue-700 mb-2">Required Information:</p>
                          <div className="bg-white rounded border border-blue-200 p-3">
                            <dl className="space-y-1">
                              {Object.entries(evaluatorDetails.scenario.required_info).map(([key, value]) => (
                                <div key={key} className="flex">
                                  <dt className="text-xs font-medium text-gray-500 w-32">{key}:</dt>
                                  <dd className="text-xs text-gray-700">{String(value)}</dd>
                                </div>
                              ))}
                            </dl>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Tags Section */}
                  <div>
                    <h3 className="text-sm font-semibold text-gray-700 mb-2 uppercase tracking-wide">Tags</h3>
                    <div className="flex flex-wrap gap-2">
                      {viewingEvaluator.tags && viewingEvaluator.tags.length > 0 ? (
                        viewingEvaluator.tags.map((tag, idx) => (
                          <span
                            key={idx}
                            className="px-3 py-1 text-sm bg-blue-100 text-blue-800 rounded-full"
                          >
                            {tag}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-gray-400">No tags</span>
                      )}
                    </div>
                  </div>

                  {/* Metadata */}
                  <div className="pt-4 border-t border-gray-200">
                    <div className="flex justify-between text-xs text-gray-500">
                      <span>Created: {new Date(viewingEvaluator.created_at).toLocaleString()}</span>
                      <span>Updated: {new Date(viewingEvaluator.updated_at).toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="py-12 text-center text-gray-500">Failed to load details</div>
              )}

              <div className="flex justify-end space-x-3 pt-6 mt-6 border-t border-gray-200">
                <Button variant="ghost" onClick={() => setViewingEvaluator(null)}>
                  Close
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    setViewingEvaluator(null)
                    handleEdit(viewingEvaluator)
                  }}
                  leftIcon={<Edit className="w-4 h-4" />}
                >
                  Edit Evaluator
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Tags Modal */}
      {editingEvaluator && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => {
                setEditingEvaluator(null)
                setEditTagInput('')
              }}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">Edit Tags - {editingEvaluator.evaluator_id}</h2>
                <button
                  onClick={() => {
                    setEditingEvaluator(null)
                    setEditTagInput('')
                  }}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="flex flex-wrap gap-2 min-h-[40px] p-2 border border-gray-200 rounded-md bg-gray-50">
                  {editingEvaluator.tags && editingEvaluator.tags.length > 0 ? (
                    editingEvaluator.tags.map((tag, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded"
                      >
                        {tag}
                        <button
                          onClick={() => {
                            const newTags = editingEvaluator.tags?.filter(t => t !== tag) || []
                            setEditingEvaluator({ ...editingEvaluator, tags: newTags })
                          }}
                          className="ml-1 text-blue-600 hover:text-blue-800"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-gray-400">No tags</span>
                  )}
                </div>

                <div className="flex space-x-2">
                  <input
                    type="text"
                    value={editTagInput}
                    onChange={(e) => setEditTagInput(e.target.value)}
                    onKeyPress={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        if (editTagInput.trim() && !editingEvaluator.tags?.includes(editTagInput.trim())) {
                          setEditingEvaluator({
                            ...editingEvaluator,
                            tags: [...(editingEvaluator.tags || []), editTagInput.trim()]
                          })
                          setEditTagInput('')
                        }
                      }
                    }}
                    placeholder="Add tag and press Enter"
                    className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                  />
                  <Button
                    size="sm"
                    onClick={() => {
                      if (editTagInput.trim() && !editingEvaluator.tags?.includes(editTagInput.trim())) {
                        setEditingEvaluator({
                          ...editingEvaluator,
                          tags: [...(editingEvaluator.tags || []), editTagInput.trim()]
                        })
                        setEditTagInput('')
                      }
                    }}
                  >
                    Add
                  </Button>
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setEditingEvaluator(null)
                      setEditTagInput('')
                    }}
                  >
                    Cancel
                  </Button>
                  <Button variant="primary" onClick={handleSaveEdit}>
                    Save Changes
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Create Evaluator Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => setShowCreateModal(false)}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">Create Evaluator</h2>
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Scenario *
                  </label>
                  <select
                    value={selectedScenario}
                    onChange={(e) => setSelectedScenario(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                  >
                    <option value="">Select a scenario</option>
                    {filteredScenarios.map((scenario: any) => (
                      <option key={scenario.id} value={scenario.id}>
                        {scenario.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Personas * ({selectedPersonas.length} selected)
                  </label>
                  <div className="border border-gray-300 rounded-md max-h-48 overflow-y-auto">
                    {filteredPersonas.length === 0 ? (
                      <div className="p-4 text-center text-gray-500">No personas available</div>
                    ) : (
                      <div className="divide-y divide-gray-200">
                        {filteredPersonas.map((persona: any) => (
                          <label
                            key={persona.id}
                            className="flex items-center p-3 hover:bg-gray-50 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedPersonas.includes(persona.id)}
                              onChange={() => togglePersona(persona.id)}
                              className="mr-3 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                            />
                            <div>
                              <div className="text-sm font-medium text-gray-900">{persona.name}</div>
                              <div className="text-xs text-gray-500">
                                {persona.language} • {persona.accent} • {persona.gender}
                              </div>
                            </div>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Tags
                  </label>
                  <div className="flex flex-wrap gap-2 mb-2">
                    {selectedTags.map((tag, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded"
                      >
                        {tag}
                        <button
                          onClick={() => removeTag(tag)}
                          className="ml-1 text-blue-600 hover:text-blue-800"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="flex space-x-2">
                    <input
                      type="text"
                      value={tagInput}
                      onChange={(e) => setTagInput(e.target.value)}
                      onKeyPress={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          addTag(selectedTags, setSelectedTags, tagInput, setTagInput)
                        }
                      }}
                      placeholder="Add tag and press Enter"
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                    />
                    <Button onClick={() => addTag(selectedTags, setSelectedTags, tagInput, setTagInput)}>Add</Button>
                  </div>
                </div>

                <div className="flex justify-end space-x-3 pt-4">
                  <Button variant="ghost" onClick={() => setShowCreateModal(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleCreate}
                    isLoading={createMutation.isPending}
                  >
                    Create Evaluators
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Running Status Indicator */}
      {runningEvaluatorIds.size > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-blue-500 rounded-full animate-pulse"></div>
              <span className="text-sm font-medium text-blue-800">
                Running {runningEvaluatorIds.size} evaluator(s) in the background. Results will appear in the Results section.
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                // Optionally clear running IDs after a delay or keep them until results appear
                queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
              }}
            >
              Refresh Results
            </Button>
          </div>
        </div>
      )}

      {/* Run Count Modal */}
      {showRunModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => setShowRunModal(false)}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">Run Evaluators</h2>
                <button
                  onClick={() => setShowRunModal(false)}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-sm text-gray-600">
                    <span className="font-medium text-gray-900">{selectedEvaluatorIds.size}</span> evaluator{selectedEvaluatorIds.size > 1 ? 's' : ''} selected
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    How many times to run each evaluator?
                  </label>
                  <div className="flex items-center space-x-3">
                    <button
                      type="button"
                      onClick={() => setRunCount(Math.max(1, runCount - 1))}
                      className="w-10 h-10 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 transition-colors"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      min="1"
                      max="50"
                      value={runCount}
                      onChange={(e) => {
                        const val = parseInt(e.target.value)
                        if (!isNaN(val) && val >= 1 && val <= 50) {
                          setRunCount(val)
                        }
                      }}
                      className="w-20 text-center px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 text-lg font-semibold"
                    />
                    <button
                      type="button"
                      onClick={() => setRunCount(Math.min(50, runCount + 1))}
                      className="w-10 h-10 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 transition-colors"
                    >
                      +
                    </button>
                  </div>
                  <p className="text-xs text-gray-500 mt-2">Maximum 50 runs per evaluator</p>
                </div>

                <div className="bg-blue-50 border border-blue-100 rounded-lg p-4">
                  <p className="text-sm text-blue-800">
                    <span className="font-semibold">{selectedEvaluatorIds.size * runCount}</span> total evaluation{selectedEvaluatorIds.size * runCount > 1 ? 's' : ''} will be queued and run in parallel.
                  </p>
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                  <Button variant="ghost" onClick={() => setShowRunModal(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="success"
                    onClick={executeRuns}
                    leftIcon={<Play className="w-4 h-4" />}
                  >
                    Run {selectedEvaluatorIds.size * runCount} Evaluation{selectedEvaluatorIds.size * runCount > 1 ? 's' : ''}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Delete Evaluator Confirmation Modal */}
      {showDeleteModal && evaluatorToDelete && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => {
                setShowDeleteModal(false)
                setEvaluatorToDelete(null)
                setDeleteDependencies(null)
              }}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Delete Evaluator</h3>
                <button
                  onClick={() => {
                    setShowDeleteModal(false)
                    setEvaluatorToDelete(null)
                    setDeleteDependencies(null)
                  }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {deleteDependencies && (
                <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-amber-800 mb-2">
                        This evaluator has dependent records
                      </p>
                      <ul className="text-xs text-amber-700 space-y-1 mb-3">
                        {deleteDependencies.evaluator_results && (
                          <li>{deleteDependencies.evaluator_results} evaluator result{deleteDependencies.evaluator_results !== 1 ? 's' : ''}</li>
                        )}
                      </ul>
                      <p className="text-xs text-amber-700">
                        Force deleting will remove the evaluator and all its results.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0">
                  <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                    <Trash2 className="h-6 w-6 text-red-600" />
                  </div>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">
                    Are you sure you want to delete evaluator <span className="font-semibold text-gray-900">#{evaluatorToDelete.evaluator_id}</span>?
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
                    setShowDeleteModal(false)
                    setEvaluatorToDelete(null)
                    setDeleteDependencies(null)
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                {deleteDependencies ? (
                  <Button
                    variant="danger"
                    onClick={() => deleteMutation.mutate({ id: evaluatorToDelete.id, force: true })}
                    isLoading={deleteMutation.isPending}
                    leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Force Delete All
                  </Button>
                ) : (
                  <Button
                    variant="danger"
                    onClick={() => deleteMutation.mutate({ id: evaluatorToDelete.id })}
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
      )}
      </div>
    </>
  )
}
