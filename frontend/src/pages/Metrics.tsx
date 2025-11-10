import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useAgentStore } from '../store/agentStore'
import { FileText, Play, Trash2, RefreshCw } from 'lucide-react'
import Button from '../components/Button'
import { format } from 'date-fns'

export default function Metrics() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Metrics Dashboard</h1>
        <p className="mt-2 text-sm text-gray-600">
          Evaluate manually transcribed conversations against agent objectives
        </p>
      </div>

      {/* Conversation Evaluation Section */}
      <ConversationEvaluationSection />
    </div>
  )
}

interface Transcription {
  id: string
  name?: string
  audio_file_key: string
  transcript: string
  created_at: string
}

interface ConversationEvaluation {
  id: string
  transcription_id: string
  agent_id: string
  objective_achieved: boolean
  objective_achieved_reason?: string
  additional_metrics?: {
    professionalism?: number
    clarity?: number
    empathy?: number
    problem_resolution?: number
    overall_quality?: number
  }
  overall_score?: number
  created_at: string
}

function ConversationEvaluationSection() {
  const { selectedAgent } = useAgentStore()
  const queryClient = useQueryClient()
  const [selectedTranscriptionId, setSelectedTranscriptionId] = useState<string | null>(null)

  // Fetch transcriptions
  const { data: transcriptions = [] } = useQuery({
    queryKey: ['manual-evaluations', 'transcriptions'],
    queryFn: () => apiClient.listManualTranscriptions(),
  })

  // Fetch evaluations for all transcriptions with the selected agent
  const { data: evaluations = [] } = useQuery({
    queryKey: ['conversation-evaluations', selectedAgent?.id],
    queryFn: async () => {
      if (!selectedAgent?.id) return []
      try {
        const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
        const apiKey = localStorage.getItem('apiKey') || ''
        const params = new URLSearchParams({ agent_id: selectedAgent.id })
        const response = await fetch(`${API_BASE_URL}/api/v1/conversation-evaluations?${params}`, {
          headers: {
            'X-API-Key': apiKey,
            'Content-Type': 'application/json',
          },
        })
        if (!response.ok) return []
        return response.json()
      } catch {
        return []
      }
    },
    enabled: !!selectedAgent?.id,
  })

  // Create evaluation mutation
  const createEvaluationMutation = useMutation({
    mutationFn: async (data: { transcription_id: string; agent_id: string }) => {
      const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
      const apiKey = localStorage.getItem('apiKey') || ''
      const response = await fetch(`${API_BASE_URL}/api/v1/conversation-evaluations`, {
        method: 'POST',
        headers: {
          'X-API-Key': apiKey,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create evaluation')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation-evaluations'] })
      setSelectedTranscriptionId(null)
    },
  })

  // Delete evaluation mutation
  const deleteEvaluationMutation = useMutation({
    mutationFn: async (evaluationId: string) => {
      const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
      const apiKey = localStorage.getItem('apiKey') || ''
      const response = await fetch(`${API_BASE_URL}/api/v1/conversation-evaluations/${evaluationId}`, {
        method: 'DELETE',
        headers: {
          'X-API-Key': apiKey,
          'Content-Type': 'application/json',
        },
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to delete evaluation')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation-evaluations'] })
    },
  })

  const handleDelete = (evaluationId: string) => {
    if (confirm('Are you sure you want to delete this evaluation?')) {
      deleteEvaluationMutation.mutate(evaluationId)
    }
  }

  const handleReEvaluate = async (transcriptionId: string, evaluationId: string) => {
    if (!selectedAgent) return
    
    // Delete existing evaluation first, then create a new one
    try {
      const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
      const apiKey = localStorage.getItem('apiKey') || ''
      
      // Delete existing evaluation
      await fetch(`${API_BASE_URL}/api/v1/conversation-evaluations/${evaluationId}`, {
        method: 'DELETE',
        headers: {
          'X-API-Key': apiKey,
          'Content-Type': 'application/json',
        },
      })
      
      // Create new evaluation
      setSelectedTranscriptionId(transcriptionId)
      createEvaluationMutation.mutate({
        transcription_id: transcriptionId,
        agent_id: selectedAgent.id,
      })
    } catch (error) {
      console.error('Failed to re-evaluate:', error)
    }
  }


  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Conversation Evaluation</h2>
        <p className="mt-1 text-sm text-gray-600">
          Evaluate manually transcribed conversations against agent objectives
        </p>
      </div>
      <div className="p-6 space-y-6">
        {/* Agent Selection Info */}
        {!selectedAgent ? (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <p className="text-sm text-yellow-800">
              Please select an agent from the top bar to evaluate conversations.
            </p>
          </div>
        ) : (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-sm text-blue-800">
              <strong>Selected Agent:</strong> {selectedAgent.name}
              {selectedAgent.description && (
                <span className="ml-2 text-blue-700">({selectedAgent.description})</span>
              )}
            </p>
          </div>
        )}


        {/* Evaluation Results Table */}
        {selectedAgent && (
          <div className="space-y-4">
            {transcriptions.length > 0 ? (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Transcription
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Professionalism
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Clarity
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Empathy
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Problem Resolution
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Overall Quality
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Objective Achieved
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {transcriptions.map((transcription: Transcription) => {
                        const evaluation = evaluations.find(
                          (e: ConversationEvaluation) => 
                            e.transcription_id === transcription.id && e.agent_id === selectedAgent.id
                        ) as ConversationEvaluation | undefined

                        const metrics = evaluation?.additional_metrics || {}
                        
                        return (
                          <tr key={transcription.id} className="hover:bg-gray-50">
                            <td className="px-6 py-4 whitespace-nowrap">
                              <div className="text-sm font-medium text-gray-900">
                                {transcription.name || transcription.audio_file_key.split('/').pop()}
                              </div>
                              <div className="text-xs text-gray-500">
                                {format(new Date(transcription.created_at), 'MMM d, yyyy')}
                              </div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              {metrics.professionalism !== undefined ? (
                                <div className="text-sm text-gray-900">
                                  {(metrics.professionalism * 100).toFixed(0)}%
                                </div>
                              ) : (
                                <span className="text-sm text-gray-400">-</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              {metrics.clarity !== undefined ? (
                                <div className="text-sm text-gray-900">
                                  {(metrics.clarity * 100).toFixed(0)}%
                                </div>
                              ) : (
                                <span className="text-sm text-gray-400">-</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              {metrics.empathy !== undefined ? (
                                <div className="text-sm text-gray-900">
                                  {(metrics.empathy * 100).toFixed(0)}%
                                </div>
                              ) : (
                                <span className="text-sm text-gray-400">-</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              {metrics.problem_resolution !== undefined ? (
                                <div className="text-sm text-gray-900">
                                  {(metrics.problem_resolution * 100).toFixed(0)}%
                                </div>
                              ) : (
                                <span className="text-sm text-gray-400">-</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              {metrics.overall_quality !== undefined ? (
                                <div className="text-sm text-gray-900">
                                  {(metrics.overall_quality * 100).toFixed(0)}%
                                </div>
                              ) : (
                                <span className="text-sm text-gray-400">-</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              {evaluation ? (
                                <span className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${
                                  evaluation.objective_achieved
                                    ? 'bg-green-100 text-green-800'
                                    : 'bg-red-100 text-red-800'
                                }`}>
                                  {evaluation.objective_achieved ? 'Yes' : 'No'}
                                </span>
                              ) : (
                                <span className="text-sm text-gray-400">-</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                              {evaluation ? (
                                <div className="flex items-center gap-2">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handleReEvaluate(transcription.id, evaluation.id)}
                                    isLoading={createEvaluationMutation.isPending && selectedTranscriptionId === transcription.id}
                                    leftIcon={<RefreshCw className="h-3 w-3" />}
                                    title="Re-evaluate"
                                  >
                                    Re-evaluate
                                  </Button>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handleDelete(evaluation.id)}
                                    isLoading={deleteEvaluationMutation.isPending}
                                    leftIcon={<Trash2 className="h-3 w-3" />}
                                    className="text-red-600 hover:text-red-700 hover:border-red-300"
                                    title="Delete evaluation"
                                  >
                                    Delete
                                  </Button>
                                </div>
                              ) : (
                                <Button
                                  variant="primary"
                                  size="sm"
                                  onClick={() => {
                                    setSelectedTranscriptionId(transcription.id)
                                    createEvaluationMutation.mutate({
                                      transcription_id: transcription.id,
                                      agent_id: selectedAgent.id,
                                    })
                                  }}
                                  isLoading={createEvaluationMutation.isPending && selectedTranscriptionId === transcription.id}
                                  leftIcon={<Play className="h-3 w-3" />}
                                >
                                  Evaluate
                                </Button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="border border-gray-200 rounded-lg p-6 text-center">
                <FileText className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                <p className="text-gray-600">No transcriptions available. Create one in the Manual Evaluations section.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

