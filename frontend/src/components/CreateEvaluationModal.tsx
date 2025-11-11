import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { EvaluationType, AudioFile, Evaluation } from '../types/api'
import { X, Loader } from 'lucide-react'

interface CreateEvaluationModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function CreateEvaluationModal({
  isOpen,
  onClose,
}: CreateEvaluationModalProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [audioId, setAudioId] = useState('')
  const [evaluationType, setEvaluationType] = useState<EvaluationType>(EvaluationType.ASR)
  const [modelName, setModelName] = useState('base')
  const [referenceText, setReferenceText] = useState('')
  const [metrics, setMetrics] = useState<string[]>(['wer', 'latency'])

  const { data: audioFiles } = useQuery<AudioFile[]>({
    queryKey: ['audio', 'list'],
    queryFn: () => apiClient.listAudio(),
    enabled: isOpen,
  })

  const createMutation = useMutation<Evaluation, Error, any>({
    mutationFn: (data: any) => apiClient.createEvaluation(data),
    onSuccess: (data: Evaluation) => {
      queryClient.invalidateQueries({ queryKey: ['evaluations'] })
      onClose()
      navigate(`/evaluations/${data.id}`)
    },
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await createMutation.mutateAsync({
        audio_id: audioId,
        evaluation_type: evaluationType,
        model_name: modelName || undefined,
        reference_text: referenceText || undefined,
        metrics: metrics.length > 0 ? metrics : undefined,
      })
    } catch (error) {
      // Error handled by mutation
    }
  }

  const toggleMetric = (metric: string) => {
    if (metrics.includes(metric)) {
      setMetrics(metrics.filter((m) => m !== metric))
    } else {
      setMetrics([...metrics, metric])
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div
          className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
          onClick={onClose}
        />
        <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold text-gray-900">Create Evaluation</h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-500"
            >
              <X className="h-6 w-6" />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Audio File
              </label>
              <select
                value={audioId}
                onChange={(e) => setAudioId(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="">Select an audio file</option>
                {audioFiles?.map((file: AudioFile) => (
                  <option key={file.id} value={file.id}>
                    {file.filename} ({(file.file_size / 1024 / 1024).toFixed(2)} MB)
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Evaluation Type
              </label>
              <select
                value={evaluationType}
                onChange={(e) => setEvaluationType(e.target.value as EvaluationType)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              >
                <option value={EvaluationType.ASR}>ASR (Automatic Speech Recognition)</option>
                <option value={EvaluationType.TTS}>TTS (Text-to-Speech)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Model Name (optional)
              </label>
              <input
                type="text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="e.g., base, small, medium, large"
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Reference Text (optional, for WER/CER)
              </label>
              <textarea
                value={referenceText}
                onChange={(e) => setReferenceText(e.target.value)}
                rows={3}
                placeholder="Enter the expected transcription text..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Metrics
              </label>
              <div className="flex flex-wrap gap-2">
                {['wer', 'cer', 'latency', 'rtf', 'quality_score'].map((metric) => (
                  <button
                    key={metric}
                    type="button"
                    onClick={() => toggleMetric(metric)}
                    className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                      metrics.includes(metric)
                        ? 'bg-primary-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {metric.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex justify-end space-x-3 pt-4">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createMutation.isPending || !audioId}
                className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50"
              >
                {createMutation.isPending ? (
                  <>
                    <Loader className="inline h-4 w-4 animate-spin mr-2" />
                    Creating...
                  </>
                ) : (
                  'Create Evaluation'
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

