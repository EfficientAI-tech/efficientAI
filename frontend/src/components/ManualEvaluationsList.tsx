import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import {
  Loader,
  Trash2,
  FileAudio,
  Mic,
  Plus,
} from 'lucide-react'
import Button from './Button'
import { format } from 'date-fns'

interface Transcription {
  id: string
  name?: string
  audio_file_key: string
  transcript: string
  speaker_segments?: Array<{
    speaker: string
    text: string
    start: number
    end: number
  }>
  stt_model?: string
  stt_provider?: string
  language?: string
  processing_time?: number
  created_at: string
  updated_at?: string
}

interface ManualEvaluationsListProps {
  onNewTranscription?: () => void
}

export default function ManualEvaluationsList(props?: ManualEvaluationsListProps) {
  const { onNewTranscription } = props || {}
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedTranscriptionId, setSelectedTranscriptionId] = useState<string | null>(null)

  // Fetch transcriptions
  const { data: transcriptions, isLoading } = useQuery({
    queryKey: ['manual-evaluations', 'transcriptions'],
    queryFn: () => apiClient.listManualTranscriptions(),
  })

  // Delete transcription mutation
  const deleteMutation = useMutation({
    mutationFn: (transcriptionId: string) => apiClient.deleteManualTranscription(transcriptionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['manual-evaluations'] })
      if (selectedTranscriptionId) {
        setSelectedTranscriptionId(null)
      }
    },
  })

  const handleDelete = async (e: React.MouseEvent, transcriptionId: string) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to delete this transcription?')) {
      try {
        await deleteMutation.mutateAsync(transcriptionId)
      } catch (error) {
        console.error('Failed to delete transcription:', error)
      }
    }
  }

  const handleRowClick = (transcriptionId: string) => {
    navigate(`/manual-evaluations/${transcriptionId}`)
  }

  const getAudioFileName = (audioFileKey: string) => {
    return audioFileKey.split('/').pop() || audioFileKey
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Manual Transcriptions</h2>
          <p className="mt-1 text-sm text-gray-600">
            View and manage your audio transcriptions
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            if (onNewTranscription) {
              onNewTranscription()
            } else {
              navigate('/evaluations?tab=manual')
            }
          }}
          leftIcon={<Plus className="h-4 w-4" />}
        >
          New Transcription
        </Button>
      </div>

      {isLoading ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        </div>
      ) : !transcriptions || transcriptions.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <Mic className="h-12 w-12 mx-auto mb-4 text-gray-400" />
          <p className="text-gray-500 mb-4">No transcriptions found</p>
          <Button
            variant="ghost"
            onClick={() => navigate('/evaluations?tab=manual')}
          >
            Create your first transcription →
          </Button>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Name / ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Audio File
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Model
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Processing Time
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Created
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {transcriptions.map((transcription: Transcription) => (
                <tr
                  key={transcription.id}
                  onClick={() => handleRowClick(transcription.id)}
                  className="cursor-pointer hover:bg-gray-50 transition-colors"
                >
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div>
                      <div className="text-sm font-medium text-gray-900">
                        {transcription.name || `Transcription ${transcription.id.slice(0, 8)}`}
                      </div>
                      <div className="text-xs text-gray-500">
                        ID: {transcription.id.slice(0, 8)}...
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center text-sm text-gray-900">
                      <FileAudio className="h-4 w-4 mr-2 text-gray-400" />
                      <span className="truncate max-w-xs">
                        {getAudioFileName(transcription.audio_file_key)}
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">
                      {transcription.stt_provider && (
                        <span className="capitalize">{transcription.stt_provider}</span>
                      )}
                      {transcription.stt_model && (
                        <span className="text-gray-500"> - {transcription.stt_model}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {transcription.processing_time
                      ? `${transcription.processing_time.toFixed(2)}s`
                      : '-'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {format(new Date(transcription.created_at), 'MMM d, yyyy HH:mm')}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={(e) => handleDelete(e, transcription.id)}
                      className="text-red-600 hover:text-red-900 inline-flex items-center"
                      title="Delete transcription"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

