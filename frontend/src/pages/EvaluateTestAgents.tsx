import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useAgentStore } from '../store/agentStore'
import Button from '../components/Button'
import { Plus, Edit, Trash2, Play, X, Tag, ChevronDown, ChevronUp } from 'lucide-react'
import VoiceAgent from '../components/VoiceAgent'

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

interface EvaluatorDetails {
  evaluator: Evaluator
  agent: any
  persona: any
  scenario: any
}

type EvaluatorDetailsOrNull = EvaluatorDetails | null

export default function EvaluateTestAgents() {
  const { selectedAgent, setSelectedAgent } = useAgentStore()
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [selectedScenario, setSelectedScenario] = useState<string>('')
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [editTagInput, setEditTagInput] = useState('')
  const [expandedEvaluator, setExpandedEvaluator] = useState<string | null>(null)
  const [editingEvaluator, setEditingEvaluator] = useState<Evaluator | null>(null)
  const [runningEvaluator, setRunningEvaluator] = useState<string | null>(null)
  const [showRunModal, setShowRunModal] = useState(false)
  const [selectedRunEvaluator, setSelectedRunEvaluator] = useState<Evaluator | null>(null)

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

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const filteredPersonas = personas.filter((p: any) => !DEFAULT_PERSONA_NAMES.includes(p.name))
  const filteredScenarios = scenarios.filter((s: any) => !DEFAULT_SCENARIO_NAMES.includes(s.name))

  // Fetch details for expanded evaluator
  const { data: evaluatorDetails } = useQuery<EvaluatorDetailsOrNull>({
    queryKey: ['evaluator-details', expandedEvaluator],
    queryFn: async (): Promise<EvaluatorDetailsOrNull> => {
      if (!expandedEvaluator) return null
      const evaluator = evaluators.find((e: Evaluator) => e.id === expandedEvaluator || e.evaluator_id === expandedEvaluator)
      if (!evaluator) return null

      const [agent, persona, scenario] = await Promise.all([
        apiClient.getAgent(evaluator.agent_id),
        apiClient.getPersona(evaluator.persona_id),
        apiClient.getScenario(evaluator.scenario_id),
      ])

      return { evaluator, agent, persona, scenario }
    },
    enabled: !!expandedEvaluator,
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
    mutationFn: (id: string) => apiClient.deleteEvaluator(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      if (expandedEvaluator) {
        setExpandedEvaluator(null)
      }
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

  const handleRun = (evaluator: Evaluator) => {
    setSelectedRunEvaluator(evaluator)
    setShowRunModal(true)
  }

  const handleStartRun = () => {
    if (!selectedRunEvaluator) return
    
    // Use the agent from the evaluator, or fall back to globally selected agent
    const evaluatorAgent = agents.find((a: any) => a.id === selectedRunEvaluator.agent_id)
    if (evaluatorAgent) {
      setSelectedAgent(evaluatorAgent)
    } else if (selectedAgent) {
      // Use globally selected agent if evaluator's agent not found
      // This should not happen, but handle gracefully
    } else {
      alert('No agent available. Please select an agent first.')
      return
    }
    
    setRunningEvaluator(selectedRunEvaluator.id)
    setShowRunModal(false)
    setSelectedRunEvaluator(null)
  }

  const handleEdit = (evaluator: Evaluator) => {
    setEditingEvaluator(evaluator)
    setExpandedEvaluator(evaluator.id)
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluator</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage evaluator configurations for testing agents with personas and scenarios
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => setShowCreateModal(true)}
          leftIcon={<Plus className="w-4 h-4" />}
        >
          Create Evaluator
        </Button>
      </div>

      {!selectedAgent && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800">
            Please select an agent from the top bar to create evaluators.
          </p>
        </div>
      )}

      {/* Evaluators List */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Evaluators</h2>
        </div>
        {loadingEvaluators ? (
          <div className="p-6 text-center text-gray-500">Loading...</div>
        ) : evaluators.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-4">No evaluators yet. Create your first evaluator to get started.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {evaluators.map((evaluator: Evaluator) => {
              const persona = personas.find((p: any) => p.id === evaluator.persona_id)
              const scenario = scenarios.find((s: any) => s.id === evaluator.scenario_id)
              const isExpanded = expandedEvaluator === evaluator.id || expandedEvaluator === evaluator.evaluator_id
              const isRunning = runningEvaluator === evaluator.id

              return (
                <div key={evaluator.id} className="p-6 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-4 flex-1">
                      <button
                        onClick={() => setExpandedEvaluator(isExpanded ? null : evaluator.id)}
                        className="flex items-center space-x-2 text-left flex-1"
                      >
                        {isExpanded ? (
                          <ChevronUp className="w-5 h-5 text-gray-400" />
                        ) : (
                          <ChevronDown className="w-5 h-5 text-gray-400" />
                        )}
                        <div>
                          <div className="flex items-center space-x-2">
                            <span className="font-mono font-semibold text-lg text-gray-900">
                              {evaluator.evaluator_id}
                            </span>
                            {evaluator.tags && evaluator.tags.length > 0 && (
                              <div className="flex items-center space-x-1">
                                <Tag className="w-4 h-4 text-gray-400" />
                                <div className="flex space-x-1">
                                  {evaluator.tags.slice(0, 3).map((tag, idx) => (
                                    <span
                                      key={idx}
                                      className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded"
                                    >
                                      {tag}
                                    </span>
                                  ))}
                                  {evaluator.tags.length > 3 && (
                                    <span className="px-2 py-0.5 text-xs text-gray-500">
                                      +{evaluator.tags.length - 3}
                                    </span>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                          <div className="text-sm text-gray-600 mt-1">
                            {persona?.name || 'Unknown Persona'} • {scenario?.name || 'Unknown Scenario'}
                          </div>
                        </div>
                      </button>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRun(evaluator)}
                        leftIcon={<Play className="w-4 h-4" />}
                        disabled={isRunning}
                      >
                        Run
                      </Button>
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
                          if (confirm('Are you sure you want to delete this evaluator?')) {
                            deleteMutation.mutate(evaluator.id)
                          }
                        }}
                        leftIcon={<Trash2 className="w-4 h-4" />}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {isExpanded && evaluatorDetails && (
                    <div className="mt-4 pt-4 border-t border-gray-200">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <h3 className="text-sm font-semibold text-gray-700 mb-2">Agent</h3>
                          <div className="bg-gray-50 rounded p-3">
                            <p className="text-sm font-medium">{evaluatorDetails.agent.name}</p>
                            {evaluatorDetails.agent.description && (
                              <p className="text-xs text-gray-600 mt-1">{evaluatorDetails.agent.description}</p>
                            )}
                            <p className="text-xs text-gray-500 mt-1">Phone: {evaluatorDetails.agent.phone_number}</p>
                          </div>
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-gray-700 mb-2">Persona</h3>
                          <div className="bg-gray-50 rounded p-3">
                            <p className="text-sm font-medium">{evaluatorDetails.persona.name}</p>
                            <div className="text-xs text-gray-600 mt-1 space-y-0.5">
                              <p>Language: {evaluatorDetails.persona.language}</p>
                              <p>Accent: {evaluatorDetails.persona.accent}</p>
                              <p>Gender: {evaluatorDetails.persona.gender}</p>
                            </div>
                          </div>
                        </div>
                        <div className="md:col-span-2">
                          <h3 className="text-sm font-semibold text-gray-700 mb-2">Scenario</h3>
                          <div className="bg-gray-50 rounded p-3">
                            <p className="text-sm font-medium">{evaluatorDetails.scenario.name}</p>
                            {evaluatorDetails.scenario.description && (
                              <p className="text-xs text-gray-600 mt-1">{evaluatorDetails.scenario.description}</p>
                            )}
                          </div>
                        </div>
                        <div className="md:col-span-2">
                          <h3 className="text-sm font-semibold text-gray-700 mb-2">Tags</h3>
                          {editingEvaluator?.id === evaluator.id ? (
                            <div className="space-y-2">
                              <div className="flex flex-wrap gap-2">
                                {editingEvaluator.tags?.map((tag, idx) => (
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
                                ))}
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
                                  placeholder="Add tag"
                                  className="flex-1 px-3 py-1 text-sm border border-gray-300 rounded-md"
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
                                <Button size="sm" variant="ghost" onClick={handleSaveEdit}>Save</Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => {
                                    setEditingEvaluator(null)
                                    setEditTagInput('')
                                  }}
                                >
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="flex flex-wrap gap-2">
                              {evaluator.tags && evaluator.tags.length > 0 ? (
                                evaluator.tags.map((tag, idx) => (
                                  <span
                                    key={idx}
                                    className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded"
                                  >
                                    {tag}
                                  </span>
                                ))
                              ) : (
                                <span className="text-sm text-gray-500">No tags</span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>

                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

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

      {/* Run Evaluator Modal */}
      {showRunModal && selectedRunEvaluator && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => {
                setShowRunModal(false)
                setSelectedRunEvaluator(null)
              }}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-4xl w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">Run Evaluator</h2>
                <button
                  onClick={() => {
                    setShowRunModal(false)
                    setSelectedRunEvaluator(null)
                  }}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Evaluator Details</h3>
                  <div className="bg-gray-50 rounded p-3 space-y-1">
                    <p className="text-sm">
                      <span className="font-medium">ID:</span> {selectedRunEvaluator.evaluator_id}
                    </p>
                    <p className="text-sm">
                      <span className="font-medium">Persona:</span>{' '}
                      {personas.find((p: any) => p.id === selectedRunEvaluator.persona_id)?.name || 'Unknown'}
                    </p>
                    <p className="text-sm">
                      <span className="font-medium">Scenario:</span>{' '}
                      {scenarios.find((s: any) => s.id === selectedRunEvaluator.scenario_id)?.name || 'Unknown'}
                    </p>
                    <p className="text-sm">
                      <span className="font-medium">Agent:</span>{' '}
                      {agents.find((a: any) => a.id === selectedRunEvaluator.agent_id)?.name || 'Unknown'}
                    </p>
                  </div>
                </div>

                <div className="flex justify-end space-x-3 pt-4">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setShowRunModal(false)
                      setSelectedRunEvaluator(null)
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleStartRun}
                  >
                    Start Call
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Voice Agent Modal for Running */}
      {runningEvaluator && (() => {
        const evaluator = evaluators.find((e: Evaluator) => e.id === runningEvaluator)
        return (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            <div className="flex min-h-screen items-center justify-center p-4">
              <div className="relative bg-white rounded-lg shadow-xl max-w-6xl w-full p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-2xl font-bold text-gray-900">Voice Agent</h2>
                  <button
                    onClick={() => setRunningEvaluator(null)}
                    className="text-gray-400 hover:text-gray-500"
                  >
                    <X className="h-6 w-6" />
                  </button>
                </div>
                <VoiceAgent
                  agentId={evaluator?.agent_id}
                  personaId={evaluator?.persona_id}
                  scenarioId={evaluator?.scenario_id}
                />
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
