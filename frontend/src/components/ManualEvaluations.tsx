import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { ModelProvider } from '../types/api'
import {
  Loader,
  Mic,
  Trash2,
  Volume2,
  FileAudio,
} from 'lucide-react'
import Button from './Button'

interface AudioFile {
  key: string
  filename: string
  size: number
  last_modified: string
}

interface Transcription {
  id: string
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
}

interface ManualEvaluationsProps {
  onBack?: () => void
}

export default function ManualEvaluations({ onBack }: ManualEvaluationsProps) {
  const [selectedFile, setSelectedFile] = useState<AudioFile | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | ''>('')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [availableProviders, setAvailableProviders] = useState<ModelProvider[]>([])
  const [enableDiarization, setEnableDiarization] = useState(true)
  const [transcriptionName, setTranscriptionName] = useState<string>('')
  const queryClient = useQueryClient()

  // Fetch audio files
  const { data: audioFiles, isLoading: filesLoading } = useQuery({
    queryKey: ['manual-evaluations', 'audio-files'],
    queryFn: () => apiClient.listManualEvaluationAudioFiles(),
  })

  // Fetch AI providers to filter available STT models
  const { data: aiProviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  // Filter providers that have STT models and are active
  useEffect(() => {
    const fetchAvailableProviders = async () => {
      try {
        const providersWithSTT: ModelProvider[] = []

        // Check each configured AI provider
        for (const provider of aiProviders) {
          if (provider.is_active) {
            try {
              const sttModels = await apiClient.getModelsByType(provider.provider, 'stt')
              if (sttModels.length > 0) {
                providersWithSTT.push(provider.provider)
              }
            } catch (error) {
              // Provider might not have STT models, skip it
              console.debug(`Provider ${provider.provider} has no STT models`)
            }
          }
        }

        setAvailableProviders(providersWithSTT)

        // Set default provider if none selected or current provider not available
        if (providersWithSTT.length > 0) {
          if (!selectedProvider || !providersWithSTT.includes(selectedProvider)) {
            setSelectedProvider(providersWithSTT[0])
          }
        } else {
          setSelectedProvider('')
          setSelectedModel('')
          setAvailableModels([])
        }
      } catch (error) {
        console.error('Failed to fetch providers:', error)
      }
    }

    fetchAvailableProviders()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiProviders])

  // Fetch models when provider changes
  useEffect(() => {
    if (!selectedProvider) {
      setAvailableModels([])
      setSelectedModel('')
      return
    }

    const fetchModels = async () => {
      try {
        const models = await apiClient.getModelsByType(selectedProvider, 'stt')
        setAvailableModels(models)
        if (models.length > 0 && !models.includes(selectedModel)) {
          setSelectedModel(models[0])
        } else if (models.length === 0) {
          setSelectedModel('')
        }
      } catch (error) {
        console.error('Failed to fetch models:', error)
        setAvailableModels([])
        setSelectedModel('')
      }
    }

    fetchModels()
  }, [selectedProvider])

  // Fetch transcriptions
  const { data: transcriptions } = useQuery({
    queryKey: ['manual-evaluations', 'transcriptions'],
    queryFn: () => apiClient.listManualTranscriptions(),
  })

  // Get transcription for selected file
  const currentTranscription = transcriptions?.find(
    (t: Transcription) => t.audio_file_key === selectedFile?.key
  )

  // Get presigned URL for audio playback
  const { data: presignedUrlData, isLoading: urlLoading } = useQuery({
    queryKey: ['manual-evaluations', 'presigned-url', selectedFile?.key],
    queryFn: () => {
      if (!selectedFile) return null
      return apiClient.getAudioPresignedUrl(selectedFile.key)
    },
    enabled: !!selectedFile,
  })

  useEffect(() => {
    if (presignedUrlData?.url) {
      setAudioUrl(presignedUrlData.url)
    }
  }, [presignedUrlData])

  // Transcription mutation
  const transcribeMutation = useMutation({
    mutationFn: (data: {
      audio_file_key: string
      stt_provider: string
      stt_model: string
      name?: string
      language?: string
      enable_speaker_diarization?: boolean
    }) => apiClient.transcribeAudio(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['manual-evaluations'] })
      // Navigate back to list if onBack is provided
      if (onBack) {
        setTimeout(() => {
          onBack()
        }, 1000) // Small delay to show success message
      }
    },
  })

  // Delete transcription mutation
  const deleteMutation = useMutation({
    mutationFn: (transcriptionId: string) => apiClient.deleteManualTranscription(transcriptionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['manual-evaluations'] })
    },
  })

  const handleTranscribe = async () => {
    if (!selectedFile || !selectedProvider || !selectedModel) return

    try {
      await transcribeMutation.mutateAsync({
        audio_file_key: selectedFile.key,
        stt_provider: selectedProvider,
        stt_model: selectedModel,
        name: transcriptionName || undefined,
        enable_speaker_diarization: enableDiarization,
      })
    } catch (error) {
      console.error('Transcription failed:', error)
    }
  }

  const handleDeleteTranscription = async (transcriptionId: string) => {
    if (confirm('Are you sure you want to delete this transcription?')) {
      try {
        await deleteMutation.mutateAsync(transcriptionId)
      } catch (error) {
        console.error('Failed to delete transcription:', error)
      }
    }
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Manual Evaluations</h2>
          <p className="mt-1 text-sm text-gray-600">
            Select audio files from S3, play them, and transcribe using STT models
          </p>
        </div>
        {onBack && (
          <Button variant="ghost" onClick={onBack}>
            Back to List
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Audio Files List */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 sm:p-6 border-b border-gray-200">
            <h3 className="text-lg font-medium text-gray-900">Audio Files</h3>
          </div>
          <div className="px-4 py-5 sm:p-6">
            {filesLoading ? (
              <div className="text-center py-8">
                <Loader className="h-6 w-6 animate-spin text-primary-600 mx-auto" />
              </div>
            ) : !audioFiles?.files || audioFiles.files.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <FileAudio className="h-12 w-12 mx-auto mb-4 text-gray-400" />
                <p>No audio files found in S3</p>
              </div>
            ) : (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {audioFiles.files.map((file: AudioFile) => (
                  <button
                    key={file.key}
                    onClick={() => setSelectedFile(file)}
                    className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                      selectedFile?.key === file.key
                        ? 'border-primary-500 bg-primary-50'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">
                          {file.filename}
                        </p>
                        <p className="text-xs text-gray-500 mt-1">
                          {formatFileSize(file.size)}
                        </p>
                      </div>
                      {transcriptions?.find((t: Transcription) => t.audio_file_key === file.key) && (
                        <div className="ml-2">
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                            Transcribed
                          </span>
                        </div>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Audio Player and Transcription */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 sm:p-6 border-b border-gray-200">
            <h3 className="text-lg font-medium text-gray-900">
              {selectedFile ? selectedFile.filename : 'Select an audio file'}
            </h3>
          </div>
          <div className="px-4 py-5 sm:p-6 space-y-6">
            {!selectedFile ? (
              <div className="text-center py-12 text-gray-500">
                <Volume2 className="h-12 w-12 mx-auto mb-4 text-gray-400" />
                <p>Select an audio file to get started</p>
              </div>
            ) : (
              <>
                {/* Audio Player */}
                <div className="bg-gray-50 rounded-lg p-4">
                  {urlLoading ? (
                    <div className="text-center py-4">
                      <Loader className="h-5 w-5 animate-spin text-primary-600 mx-auto" />
                    </div>
                  ) : audioUrl ? (
                    <audio
                      src={audioUrl}
                      className="w-full"
                      controls
                    />
                  ) : (
                    <div className="text-center py-4 text-gray-500">
                      Failed to load audio
                    </div>
                  )}
                </div>

                {/* Transcription Controls */}
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      STT Provider
                    </label>
                    {availableProviders.length === 0 ? (
                      <div className="px-3 py-2 border border-gray-300 rounded-md bg-gray-50 text-gray-500 text-sm">
                        No AI providers configured. Please configure an AI provider with STT models first.
                      </div>
                    ) : (
                      <select
                        value={selectedProvider}
                        onChange={(e) => {
                          const newProvider = e.target.value as ModelProvider
                          setSelectedProvider(newProvider)
                          // Update models when provider changes
                          const fetchModels = async () => {
                            try {
                              const models = await apiClient.getModelsByType(newProvider, 'stt')
                              setAvailableModels(models)
                              if (models.length > 0) {
                                setSelectedModel(models[0])
                              }
                            } catch (error) {
                              console.error('Failed to fetch models:', error)
                            }
                          }
                          fetchModels()
                        }}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                      >
                        {availableProviders.map((provider) => (
                          <option key={provider} value={provider}>
                            {provider.charAt(0) + provider.slice(1).toLowerCase()}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      STT Model
                    </label>
                    {!selectedProvider || availableModels.length === 0 ? (
                      <div className="px-3 py-2 border border-gray-300 rounded-md bg-gray-50 text-gray-500 text-sm">
                        {!selectedProvider ? 'Select a provider first' : 'No STT models available for this provider'}
                      </div>
                    ) : (
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                      >
                        {availableModels.map((model) => (
                          <option key={model} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Transcription Name (Optional)
                    </label>
                    <input
                      type="text"
                      value={transcriptionName}
                      onChange={(e) => setTranscriptionName(e.target.value)}
                      placeholder="Enter a name for this transcription"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      If left empty, a default name will be generated
                    </p>
                  </div>

                  <div className="flex items-center">
                    <input
                      type="checkbox"
                      id="diarization"
                      checked={enableDiarization}
                      onChange={(e) => setEnableDiarization(e.target.checked)}
                      className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                    />
                    <label htmlFor="diarization" className="ml-2 block text-sm text-gray-700">
                      Enable speaker diarization (detect multiple speakers)
                    </label>
                  </div>

                  <Button
                    variant="primary"
                    onClick={handleTranscribe}
                    disabled={transcribeMutation.isPending || !selectedProvider || !selectedModel}
                    leftIcon={transcribeMutation.isPending ? <Loader className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
                    className="w-full"
                  >
                    {transcribeMutation.isPending ? 'Transcribing...' : 'Transcribe Audio'}
                  </Button>
                </div>

                {/* Transcription Results */}
                {currentTranscription && (
                  <div className="mt-6 pt-6 border-t border-gray-200">
                    <div className="flex items-center justify-between mb-4">
                      <h4 className="text-sm font-medium text-gray-900">Transcription</h4>
                      <button
                        onClick={() => handleDeleteTranscription(currentTranscription.id)}
                        className="text-red-600 hover:text-red-800"
                        title="Delete transcription"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    {currentTranscription.speaker_segments && currentTranscription.speaker_segments.length > 0 ? (
                      <div className="space-y-3">
                        {currentTranscription.speaker_segments.map((segment: { speaker: string; text: string; start: number; end: number }, idx: number) => (
                          <div key={idx} className="bg-gray-50 rounded-lg p-3">
                            <div className="flex items-center mb-1">
                              <span className="text-xs font-medium text-primary-600">
                                {segment.speaker}
                              </span>
                              <span className="ml-2 text-xs text-gray-500">
                                {segment.start.toFixed(1)}s - {segment.end.toFixed(1)}s
                              </span>
                            </div>
                            <p className="text-sm text-gray-700">{segment.text}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="bg-gray-50 rounded-lg p-4">
                        <p className="text-sm text-gray-700 whitespace-pre-wrap">
                          {currentTranscription.transcript}
                        </p>
                      </div>
                    )}

                    {currentTranscription.stt_model && (
                      <div className="mt-4 text-xs text-gray-500">
                        Model: {currentTranscription.stt_model} • 
                        {currentTranscription.processing_time && (
                          <> Processing: {currentTranscription.processing_time.toFixed(2)}s</>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {transcribeMutation.isError && (
                  <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                    <p className="text-sm text-red-800">
                      {transcribeMutation.error instanceof Error
                        ? transcribeMutation.error.message
                        : 'Transcription failed'}
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

