import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import ConfirmModal from '../components/ConfirmModal'
import { ArrowLeft, RefreshCw, Trash2, BarChart3, CheckCircle, XCircle, HelpCircle, Brain, Sparkles, AudioWaveform, Loader } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'
import RetellCallDetails from '../components/call-recordings/RetellCallDetails'
import VapiCallDetails from '../components/call-recordings/VapiCallDetails'

// Comprehensive metric information with descriptions and ideal values
const METRIC_INFO: Record<string, { 
  description: string
  ideal: string
  unit?: string
  category: 'acoustic' | 'ai_voice' | 'llm'
}> = {
  // Acoustic Metrics (Parselmouth)
  'Pitch Variance': { 
    description: 'F0 variation measuring prosodic expressiveness. Higher values indicate more expressive speech.',
    ideal: '20-50 Hz (natural speech)',
    unit: 'Hz',
    category: 'acoustic'
  },
  'Jitter': { 
    description: 'Cycle-to-cycle pitch period variation indicating vocal stability. Lower is better.',
    ideal: '< 1% (healthy voice)',
    unit: '%',
    category: 'acoustic'
  },
  'Shimmer': { 
    description: 'Amplitude perturbation measuring voice quality consistency. Lower is better.',
    ideal: '< 3% (clear voice)',
    unit: '%',
    category: 'acoustic'
  },
  'HNR': { 
    description: 'Harmonics-to-Noise Ratio measuring signal clarity. Higher indicates cleaner voice.',
    ideal: '> 20 dB (clear, non-breathy)',
    unit: 'dB',
    category: 'acoustic'
  },
  
  // AI Voice Quality Metrics
  'MOS Score': { 
    description: 'Mean Opinion Score predicting human perception of audio quality (1-5 scale).',
    ideal: '4.0+ (studio quality), 3.0 (phone quality), <2.0 (poor/robotic)',
    category: 'ai_voice'
  },
  'Emotion Category': { 
    description: 'Dominant emotion detected in the voice (angry, happy, sad, neutral, fearful, etc.).',
    ideal: 'Depends on context - should match expected tone',
    category: 'ai_voice'
  },
  'Emotion Confidence': { 
    description: 'Confidence score for the detected emotion category.',
    ideal: '> 0.7 (high confidence)',
    category: 'ai_voice'
  },
  'Valence': { 
    description: 'Emotional positivity/negativity scale. Negative = sad/angry, Positive = happy/excited.',
    ideal: '-1.0 to +1.0 (context dependent)',
    category: 'ai_voice'
  },
  'Arousal': { 
    description: 'Emotional intensity/energy level. Low = calm/sleepy, High = excited/energetic.',
    ideal: '0.3-0.6 (engaged but not agitated)',
    category: 'ai_voice'
  },
  'Speaker Consistency': { 
    description: 'Voice identity stability throughout the call. Detects if voice changed mid-call (glitch).',
    ideal: '> 0.8 (same voice), < 0.5 indicates voice glitch',
    category: 'ai_voice'
  },
  'Prosody Score': { 
    description: 'Expressiveness/drama score. Low = monotone/flat, High = expressive/dynamic.',
    ideal: '0.4-0.7 (natural expressiveness)',
    category: 'ai_voice'
  },
  
  // LLM Conversation Metrics
  'Follow Instructions': { 
    description: 'How well the agent followed the given instructions and guidelines.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Problem Resolution': { 
    description: 'Whether the agent successfully resolved the customer\'s problem or query.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Professionalism': { 
    description: 'Professional demeanor, appropriate language, and courteous behavior.',
    ideal: '> 0.85 (85%+)',
    category: 'llm'
  },
  'Clarity and Empathy': { 
    description: 'Clear communication combined with understanding and acknowledgment of customer feelings.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Objective Achieved': { 
    description: 'Whether the conversation\'s primary objective was successfully achieved.',
    ideal: 'Yes/True',
    category: 'llm'
  },
  'Overall Quality': { 
    description: 'Holistic assessment of the entire conversation quality.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
}

const getMetricInfo = (metricName: string) => METRIC_INFO[metricName]

const isAudioMetric = (metricName: string): boolean => {
  const info = METRIC_INFO[metricName]
  return info?.category === 'acoustic' || info?.category === 'ai_voice'
}

const getAudioMetricInfo = (metricName: string) => {
  const info = METRIC_INFO[metricName]
  if (!info) return undefined
  return { unit: info.unit || '', description: info.description }
}

// Tooltip component for metrics
const MetricTooltip = ({ metricName }: { metricName: string }) => {
  const [isVisible, setIsVisible] = useState(false)
  const info = getMetricInfo(metricName)
  
  if (!info) return null
  
  return (
    <div className="relative inline-block ml-1">
      <button
        type="button"
        className="text-gray-400 hover:text-gray-600 focus:outline-none transition-colors"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onClick={() => setIsVisible(!isVisible)}
        aria-label={`Info about ${metricName}`}
      >
        <HelpCircle className="w-3.5 h-3.5" />
      </button>
      
      {isVisible && (
        <div className="absolute z-50 left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 p-3 text-xs bg-gray-900 text-white rounded-lg shadow-xl pointer-events-none">
          <div className="font-semibold text-gray-100 mb-1.5">{metricName}</div>
          <p className="text-gray-300 mb-2 leading-relaxed">{info.description}</p>
          <div className="flex items-center gap-1 pt-1.5 border-t border-gray-700">
            <span className="text-emerald-400 font-medium">Ideal:</span>
            <span className="text-gray-200">{info.ideal}</span>
          </div>
          {/* Arrow pointing down */}
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-gray-900" />
        </div>
      )}
    </div>
  )
}

// Format metric value for display
const formatMetricValue = (value: any, type: string, metricName?: string): React.ReactNode => {
  if (value === null || value === undefined) return <span className="text-gray-400">N/A</span>
  
  const normalizedType = type?.toLowerCase()
  
  // Handle Emotion Category - categorical text values with styling
  if (metricName === 'Emotion Category') {
    const emotion = String(value).toLowerCase()
    const emotionConfig: Record<string, { emoji: string; color: string; bg: string }> = {
      'neutral': { emoji: '😐', color: 'text-gray-700', bg: 'bg-gray-100' },
      'happy': { emoji: '😊', color: 'text-green-700', bg: 'bg-green-100' },
      'sad': { emoji: '😢', color: 'text-blue-700', bg: 'bg-blue-100' },
      'angry': { emoji: '😠', color: 'text-red-700', bg: 'bg-red-100' },
      'fearful': { emoji: '😨', color: 'text-purple-700', bg: 'bg-purple-100' },
      'fear': { emoji: '😨', color: 'text-purple-700', bg: 'bg-purple-100' },
      'surprised': { emoji: '😲', color: 'text-yellow-700', bg: 'bg-yellow-100' },
      'surprise': { emoji: '😲', color: 'text-yellow-700', bg: 'bg-yellow-100' },
      'disgusted': { emoji: '🤢', color: 'text-green-800', bg: 'bg-green-200' },
      'disgust': { emoji: '🤢', color: 'text-green-800', bg: 'bg-green-200' },
      'calm': { emoji: '😌', color: 'text-teal-700', bg: 'bg-teal-100' },
    }
    const config = emotionConfig[emotion] || { emoji: '🎭', color: 'text-gray-700', bg: 'bg-gray-100' }
    
    return (
      <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${config.bg}`}>
        <span className="text-xl">{config.emoji}</span>
        <span className={`font-semibold capitalize ${config.color}`}>{value}</span>
      </div>
    )
  }
  
  // Handle boolean metrics
  if (normalizedType === 'boolean') {
    const boolValue = value === true || value === 1 || value === '1' || value === 'true'
    return boolValue ? (
      <div className="flex items-center space-x-1.5 text-green-600">
        <CheckCircle className="w-5 h-5" />
        <span className="font-semibold">Yes</span>
      </div>
    ) : (
      <div className="flex items-center space-x-1.5 text-red-600">
        <XCircle className="w-5 h-5" />
        <span className="font-semibold">No</span>
      </div>
    )
  }
  
  // Handle rating metrics with progress bar
  if (normalizedType === 'rating') {
    if (typeof value === 'string' && isNaN(parseFloat(value))) {
      return (
        <span className="inline-flex items-center px-3 py-1.5 rounded-full bg-purple-100 text-purple-700 font-semibold capitalize">
          {value}
        </span>
      )
    }
    
    const numValue = typeof value === 'number' ? value : parseFloat(value)
    if (isNaN(numValue)) return <span className="text-gray-400">N/A</span>
    
    const normalizedValue = Math.max(0, Math.min(1, numValue))
    const percentage = Math.round(normalizedValue * 100)
    
    const getBarColor = (pct: number): string => {
      if (pct >= 70) return 'bg-green-500'
      if (pct >= 50) return 'bg-yellow-500'
      return 'bg-red-500'
    }
    
    return (
      <div className="flex flex-col gap-2">
        <span className="text-2xl font-bold text-gray-900">{percentage}%</span>
        <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
          <div 
            className={`h-full rounded-full transition-all ${getBarColor(percentage)}`}
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>
    )
  }
  
  // Handle number metrics (including audio metrics)
  if (normalizedType === 'number') {
    const numValue = typeof value === 'number' ? value : parseFloat(value)
    if (isNaN(numValue)) return <span className="text-gray-400">N/A</span>
    
    if (metricName && isAudioMetric(metricName)) {
      const audioInfo = getAudioMetricInfo(metricName)
      return (
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-bold text-gray-900">{numValue.toFixed(2)}</span>
          <span className="text-sm font-medium text-violet-600">{audioInfo?.unit}</span>
        </div>
      )
    }
    
    return <span className="text-2xl font-bold text-gray-900">{numValue.toFixed(1)}</span>
  }
  
  return <span className="text-2xl font-bold text-gray-900">{String(value)}</span>
}

// Helper to check if a metric has a valid value
const hasValidValue = (metric: { value: any }) => {
  const val = metric.value
  if (val === null || val === undefined) return false
  if (val === '') return false
  if (typeof val === 'string' && val.toLowerCase() === 'n/a') return false
  if (typeof val === 'string' && val.toLowerCase() === 'na') return false
  if (typeof val === 'string' && val.trim() === '') return false
  return true
}

export default function CallRecordingDetail() {
  const { callShortId } = useParams<{ callShortId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showDelete, setShowDelete] = useState(false)

  const { data: callRecording, refetch: refetchCallDetails, isLoading } = useQuery({
    queryKey: ['call-recording', callShortId],
    queryFn: () => apiClient.getCallRecording(callShortId!),
    enabled: !!callShortId,
    // Refetch every 5 seconds if evaluation is in progress
    refetchInterval: (query) => {
      const data = query.state.data as any
      if (data?.evaluation?.status && ['queued', 'transcribing', 'evaluating'].includes(data.evaluation.status)) {
        return 5000
      }
      return false
    },
  })

  const refreshMutation = useMutation({
    mutationFn: () => apiClient.refreshCallRecording(callShortId!),
    onSuccess: () => {
      showToast('Call recording refresh initiated', 'success')
      setTimeout(() => {
        refetchCallDetails()
      }, 2000)
    },
    onError: (error: any) => {
      showToast(`Failed to refresh: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteCallRecording(callShortId!),
    onSuccess: () => {
      showToast('Call recording deleted successfully', 'success')
      queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
      navigate('/playground')
    },
    onError: (error: any) => {
      showToast(`Failed to delete: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const handleDelete = () => {
    setShowDelete(true)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-600">Loading call recording...</div>
      </div>
    )
  }

  if (!callRecording) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-gray-600 mb-4">Call recording not found</p>
          <Button variant="outline" onClick={() => navigate('/playground')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Playground
          </Button>
        </div>
      </div>
    )
  }

  return (
    <>
      <ToastContainer />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <Button
            variant="outline"
            onClick={() => navigate('/playground')}
            leftIcon={<ArrowLeft className="h-4 w-4" />}
            className="mb-4"
          >
            Back to Playground
          </Button>
          <div className="bg-white shadow rounded-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Call Recording Details</h1>
                <p className="text-sm text-gray-500 mt-1">
                  Call ID: <span className="font-mono">{callRecording.call_short_id}</span>
                </p>
              </div>
              <div className="flex gap-2">
                {callRecording.status === 'PENDING' && (
                  <Button
                    variant="outline"
                    onClick={() => refreshMutation.mutate()}
                    leftIcon={<RefreshCw className="h-4 w-4" />}
                    isLoading={refreshMutation.isPending}
                  >
                    Refresh
                  </Button>
                )}
                <Button
                  variant="danger"
                  onClick={handleDelete}
                  leftIcon={<Trash2 className="h-4 w-4" />}
                  isLoading={deleteMutation.isPending}
                >
                  Delete
                </Button>
              </div>
            </div>

            {/* Metadata */}
            <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
                <span
                  className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${callRecording.status === 'UPDATED'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-yellow-100 text-yellow-800'
                    }`}
                >
                  {callRecording.status}
                </span>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Evaluation</p>
                {callRecording.evaluation ? (
                  <span
                    className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                      callRecording.evaluation.status === 'completed'
                        ? 'bg-green-100 text-green-800'
                        : callRecording.evaluation.status === 'failed'
                        ? 'bg-red-100 text-red-800'
                        : callRecording.evaluation.status === 'evaluating'
                        ? 'bg-blue-100 text-blue-800'
                        : 'bg-yellow-100 text-yellow-800'
                    }`}
                  >
                    {callRecording.evaluation.status || 'queued'}
                  </span>
                ) : (
                  <span className="text-sm text-gray-500">Pending</span>
                )}
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Platform</p>
                <p className="text-sm text-gray-900">{callRecording.provider_platform || 'N/A'}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Provider Call ID</p>
                <p className="text-sm font-mono text-gray-900 text-xs">
                  {callRecording.provider_call_id || 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Created</p>
                <p className="text-sm text-gray-900">
                  {callRecording.created_at
                    ? new Date(callRecording.created_at).toLocaleString()
                    : 'N/A'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Evaluation Metrics Section */}
        {callRecording.evaluation && (
          <div className="mb-6 bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold text-gray-900 flex items-center mb-4">
              <BarChart3 className="w-5 h-5 mr-2" />
              Evaluation Metrics
              {callRecording.evaluation.result_id && (
                <span className="ml-2 text-sm font-mono text-gray-500">
                  #{callRecording.evaluation.result_id}
                </span>
              )}
            </h2>
            
            {callRecording.evaluation.status === 'completed' && callRecording.evaluation.metric_scores && Object.keys(callRecording.evaluation.metric_scores).length > 0 ? (
              (() => {
                const metricScores = callRecording.evaluation.metric_scores
                
                // Categorize metrics - only include those with valid values
                const acousticMetrics = Object.entries(metricScores).filter(
                  ([, metric]: [string, any]) => {
                    if (!hasValidValue(metric)) return false
                    const info = getMetricInfo(metric.metric_name || '')
                    return info?.category === 'acoustic'
                  }
                )
                const aiVoiceMetrics = Object.entries(metricScores).filter(
                  ([, metric]: [string, any]) => {
                    if (!hasValidValue(metric)) return false
                    const info = getMetricInfo(metric.metric_name || '')
                    return info?.category === 'ai_voice'
                  }
                )
                const llmMetrics = Object.entries(metricScores).filter(
                  ([, metric]: [string, any]) => {
                    if (!hasValidValue(metric)) return false
                    const info = getMetricInfo(metric.metric_name || '')
                    return !info || info.category === 'llm'
                  }
                )
                
                return (
                  <div className="space-y-6">
                    {/* AI Voice Quality Metrics */}
                    {aiVoiceMetrics.length > 0 && (
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Sparkles className="w-4 h-4 text-purple-600" />
                          <h3 className="text-sm font-semibold text-purple-800 uppercase tracking-wide">AI Voice Quality</h3>
                          <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-700 rounded-full">ML Analysis</span>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                          {aiVoiceMetrics.map(([metricId, metric]: [string, any]) => (
                            <div key={metricId} className="border border-purple-200 bg-purple-50/50 rounded-lg p-4">
                              <div className="text-sm font-medium text-purple-700 mb-2 flex items-center">
                                <span>{metric.metric_name || metricId}</span>
                                <MetricTooltip metricName={metric.metric_name || metricId} />
                              </div>
                              <div>
                                {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    
                    {/* Acoustic Metrics (Parselmouth) */}
                    {acousticMetrics.length > 0 && (
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <AudioWaveform className="w-4 h-4 text-violet-600" />
                          <h3 className="text-sm font-semibold text-violet-800 uppercase tracking-wide">Acoustic Metrics</h3>
                          <span className="px-2 py-0.5 text-xs bg-violet-100 text-violet-700 rounded-full">Signal Analysis</span>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                          {acousticMetrics.map(([metricId, metric]: [string, any]) => (
                            <div key={metricId} className="border border-violet-200 bg-violet-50/50 rounded-lg p-4">
                              <div className="text-sm font-medium text-violet-700 mb-2 flex items-center">
                                <span>{metric.metric_name || metricId}</span>
                                <MetricTooltip metricName={metric.metric_name || metricId} />
                              </div>
                              <div>
                                {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    
                    {/* LLM-based Metrics */}
                    {llmMetrics.length > 0 && (
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Brain className="w-4 h-4 text-emerald-600" />
                          <h3 className="text-sm font-semibold text-emerald-800 uppercase tracking-wide">Conversation Metrics</h3>
                          <span className="px-2 py-0.5 text-xs bg-emerald-100 text-emerald-700 rounded-full">LLM Evaluation</span>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                          {llmMetrics.map(([metricId, metric]: [string, any]) => (
                            <div key={metricId} className="border border-gray-200 rounded-lg p-4">
                              <div className="text-sm font-medium text-gray-500 mb-2 flex items-center">
                                <span>{metric.metric_name || metricId}</span>
                                <MetricTooltip metricName={metric.metric_name || metricId} />
                              </div>
                              <div>
                                {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })()
            ) : callRecording.evaluation.status === 'evaluating' || callRecording.evaluation.status === 'transcribing' ? (
              <div className="flex items-center justify-center py-8">
                <Loader className="w-6 h-6 text-blue-500 animate-spin mr-3" />
                <span className="text-gray-600">
                  {callRecording.evaluation.status === 'transcribing' ? 'Transcribing audio...' : 'Evaluating conversation...'}
                </span>
              </div>
            ) : callRecording.evaluation.status === 'failed' ? (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
                <XCircle className="w-6 h-6 text-red-500 mx-auto mb-2" />
                <p className="text-red-700">Evaluation failed. Please try again.</p>
              </div>
            ) : callRecording.evaluation.status === 'queued' ? (
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
                <Loader className="w-6 h-6 text-yellow-500 mx-auto mb-2" />
                <p className="text-yellow-700">Evaluation queued and will start shortly...</p>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                No evaluation metrics available yet.
              </div>
            )}
          </div>
        )}

        {/* Call Data */}
        <div className="bg-white shadow rounded-lg p-6">
          {callRecording.call_data ? (
            <>
              {callRecording.provider_platform === 'retell' ? (
                <RetellCallDetails callData={callRecording.call_data} />
              ) : callRecording.provider_platform === 'vapi' ? (
                <VapiCallDetails callData={callRecording.call_data} />
              ) : (
                <>
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">Call Data (JSON)</h2>
                  <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs max-h-[600px]">
                    {JSON.stringify(callRecording.call_data, null, 2)}
                  </pre>
                </>
              )}
            </>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No call data available. Try refreshing if the call just ended.
            </div>
          )}
        </div>
      </div>

      <ConfirmModal
        title="Delete call recording"
        description="This will permanently remove this playground call recording."
        isOpen={showDelete}
        isLoading={deleteMutation.isPending}
        onCancel={() => setShowDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
      />
    </>
  )
}
