import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  ArrowLeft, Phone, Clock, PhoneIncoming, PhoneOutgoing,
  MessageSquare, Trash2, Download, Tag, ExternalLink,
  ChevronDown, ChevronUp, Loader, XCircle, Sparkles, X,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import Button from '../components/Button'
import ConfirmModal from '../components/ConfirmModal'
import { apiClient } from '../lib/api'
import RetellCallDetails from '../components/call-recordings/RetellCallDetails'
import VapiCallDetails from '../components/call-recordings/VapiCallDetails'

export default function ObservabilityCallDetail() {
  const navigate = useNavigate()
  const { callShortId } = useParams<{ callShortId: string }>()
  const queryClient = useQueryClient()
  const [showDelete, setShowDelete] = useState(false)
  const [showRawData, setShowRawData] = useState(false)
  const [showEvalModal, setShowEvalModal] = useState(false)
  const [selectedEvaluator, setSelectedEvaluator] = useState('')

  const {
    data: callRecording,
    isLoading,
  } = useQuery({
    queryKey: ['observability-call', callShortId],
    queryFn: () => apiClient.getObservabilityCall(callShortId!),
    enabled: !!callShortId,
  })

  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
    enabled: showEvalModal,
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteObservabilityCall(callShortId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
      navigate('/observability/calls')
    },
  })

  const evaluateMutation = useMutation({
    mutationFn: (evaluatorId: string) =>
      apiClient.evaluateObservabilityCall(callShortId!, evaluatorId),
    onSuccess: (data) => {
      setShowEvalModal(false)
      setSelectedEvaluator('')
      navigate(`/results/${data.result_id}`)
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <Loader className="w-8 h-8 text-indigo-500 animate-spin mx-auto" />
          <p className="text-sm text-gray-500 mt-3">Loading call details...</p>
        </div>
      </div>
    )
  }

  if (!callRecording) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-6 text-center">
          <XCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
          <p className="text-sm font-medium text-rose-800">Call not found</p>
          <Button
            onClick={() => navigate('/observability/calls')}
            variant="ghost"
            size="sm"
            className="mt-4"
          >
            <ArrowLeft className="w-4 h-4 mr-1.5" />
            Back to Calls
          </Button>
        </div>
      </div>
    )
  }

  const callData = callRecording.call_data
  const messages: any[] | undefined = callData?.messages
  const hasMessages = Array.isArray(messages) && messages.length > 0

  const computeDuration = (): string | null => {
    if (!callData?.startedAt || !callData?.endedAt) return null
    const start = new Date(callData.startedAt).getTime()
    const end = new Date(callData.endedAt).getTime()
    if (isNaN(start) || isNaN(end)) return null
    const diffSec = Math.floor((end - start) / 1000)
    const mins = Math.floor(diffSec / 60)
    const secs = diffSec % 60
    return `${mins}m ${secs}s`
  }

  const formatMessageTime = (timestamp: number): string => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const duration = computeDuration()

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="outline"
          onClick={() => navigate('/observability/calls')}
          leftIcon={<ArrowLeft className="h-4 w-4" />}
          className="mb-4"
        >
          Back to Calls
        </Button>

        <div className="bg-white shadow rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Call Details</h1>
              <p className="text-sm text-gray-500 mt-1">
                Call ID:{' '}
                <span className="font-mono font-semibold text-primary-600">
                  {callRecording.call_short_id}
                </span>
              </p>
            </div>
            <div className="flex items-center gap-3">
              {hasMessages && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setShowEvalModal(true)}
                  leftIcon={<Sparkles className="h-4 w-4" />}
                >
                  Run Evaluation
                </Button>
              )}
              <Button
                variant="danger"
                size="sm"
                onClick={() => setShowDelete(true)}
                isLoading={deleteMutation.isPending}
                leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
              >
                Delete
              </Button>
              <EventBadge event={callRecording.call_event} />
            </div>
          </div>

          {/* Metadata grid */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                  callRecording.status === 'updated'
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-yellow-50 text-yellow-700 border-yellow-200'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    callRecording.status === 'updated' ? 'bg-emerald-500' : 'bg-yellow-500'
                  }`}
                />
                {callRecording.status === 'updated' ? 'Received' : callRecording.status}
              </span>
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Platform</p>
              <PlatformBadge platform={callRecording.provider_platform} />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Provider Call ID</p>
              <p
                className="text-sm font-mono text-gray-900 text-xs truncate max-w-[180px]"
                title={callRecording.provider_call_id}
              >
                {callRecording.provider_call_id || 'N/A'}
              </p>
            </div>
            {duration && (
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Duration</p>
                <p className="text-sm text-gray-900 flex items-center">
                  <Clock className="w-4 h-4 mr-1" />
                  {duration}
                </p>
              </div>
            )}
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

      {/* Provider-specific call details (Call Analysis, Cost, Latency, System Details) */}
      {callRecording.provider_platform === 'retell' && callData && (
        <div className="mb-6 bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Provider Call Details
            <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded-full">
              retell
            </span>
          </h2>
          <RetellCallDetails callData={callData} hideTranscript={hasMessages} />
        </div>
      )}

      {callRecording.provider_platform === 'vapi' && callData && (
        <div className="mb-6 bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Provider Call Details
            <span className="ml-2 px-2 py-0.5 text-xs bg-violet-100 text-violet-800 rounded-full">
              vapi
            </span>
          </h2>
          <VapiCallDetails callData={callData} hideTranscript={hasMessages} />
        </div>
      )}

      {/* Structured transcript with sidebar */}
      {hasMessages && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          {/* Left: Transcript */}
          <div className="lg:col-span-2">
            <div className="rounded-xl border border-gray-100 bg-gray-50/30 flex flex-col h-[560px]">
              <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-indigo-500" />
                  <span className="text-sm font-medium text-gray-900">Transcript</span>
                  <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                    {messages!.length} messages
                  </span>
                </div>
                {callData?.recording_url && (
                  <div className="flex items-center gap-2">
                    <audio controls src={callData.recording_url} className="h-8 w-56" />
                    <a
                      href={callData.recording_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  </div>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {messages!.map((msg: any, index: number) => {
                  const isUser = msg.role === 'user'

                  return (
                    <motion.div
                      key={index}
                      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.2, delay: index * 0.03 }}
                    >
                      <div
                        className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                          isUser
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                        }`}
                      >
                        <div
                          className={`flex items-center gap-2 mb-0.5 ${
                            isUser ? 'text-indigo-200' : 'text-gray-400'
                          }`}
                        >
                          <span className="text-[10px] font-semibold uppercase tracking-wider">
                            {isUser ? 'Caller' : 'Agent'}
                          </span>
                          {msg.start_time && (
                            <span className="text-[10px] tabular-nums">
                              {formatMessageTime(msg.start_time)}
                            </span>
                          )}
                        </div>
                        <p className="text-sm leading-relaxed">{msg.content}</p>
                      </div>
                    </motion.div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Right: Call Summary */}
          <div className="lg:col-span-1 space-y-4">
            <div className="rounded-xl border border-gray-100 bg-gray-50/30 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Phone className="h-4 w-4 text-indigo-500" />
                Call Summary
              </h3>
              <div className="space-y-3">
                {duration && (
                  <div className="p-3 bg-white rounded-lg border border-gray-100">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">
                      Duration
                    </p>
                    <p className="text-base font-semibold text-gray-900 tabular-nums">{duration}</p>
                  </div>
                )}

                {callData?.startedAt && (
                  <div className="p-3 bg-white rounded-lg border border-gray-100">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">
                      Started At
                    </p>
                    <p className="text-sm text-gray-900">
                      {new Date(callData.startedAt).toLocaleString()}
                    </p>
                  </div>
                )}

                {callData?.endedAt && (
                  <div className="p-3 bg-white rounded-lg border border-gray-100">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">
                      Ended At
                    </p>
                    <p className="text-sm text-gray-900">
                      {new Date(callData.endedAt).toLocaleString()}
                    </p>
                  </div>
                )}

                {(callData?.from_phone_number || callData?.to_phone_number) && (
                  <div className="p-3 bg-white rounded-lg border border-gray-100">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">
                      Phone Numbers
                    </p>
                    <div className="space-y-2 mt-1.5">
                      {callData.from_phone_number && (
                        <div className="flex items-center gap-2">
                          <PhoneOutgoing className="w-3.5 h-3.5 text-gray-400" />
                          <span className="text-sm text-gray-700 font-mono">
                            {callData.from_phone_number}
                          </span>
                        </div>
                      )}
                      {callData.to_phone_number && (
                        <div className="flex items-center gap-2">
                          <PhoneIncoming className="w-3.5 h-3.5 text-gray-400" />
                          <span className="text-sm text-gray-700 font-mono">
                            {callData.to_phone_number}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {callData?.endedReason && (
                  <div className="p-3 bg-white rounded-lg border border-gray-100">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">
                      End Reason
                    </p>
                    <EndReasonBadge reason={callData.endedReason} />
                  </div>
                )}

                {callData?.metadata &&
                  Object.keys(callData.metadata).length > 0 && (
                    <div className="p-3 bg-white rounded-lg border border-gray-100">
                      <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-2">
                        Metadata
                      </p>
                      <div className="space-y-1.5">
                        {Object.entries(callData.metadata).map(([key, value]) => (
                          <div key={key} className="flex items-start gap-2">
                            <Tag className="w-3 h-3 text-gray-300 mt-0.5 flex-shrink-0" />
                            <div className="min-w-0">
                              <span className="text-xs text-gray-500">{key}:</span>
                              <span className="text-xs text-gray-800 ml-1 font-medium">
                                {String(value)}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                {callData?.recording_url && (
                  <div className="p-3 bg-white rounded-lg border border-gray-100">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">
                      Recording
                    </p>
                    <a
                      href={callData.recording_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-indigo-600 hover:text-indigo-800 flex items-center gap-1.5 mt-1"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Download Recording
                    </a>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Generic fallback: raw JSON for calls without messages and not from a known provider */}
      {!hasMessages &&
        callRecording.provider_platform !== 'retell' &&
        callRecording.provider_platform !== 'vapi' &&
        callData && (
          <div className="mb-6 bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Call Data</h2>
            <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs max-h-[600px]">
              {JSON.stringify(callData, null, 2)}
            </pre>
          </div>
        )}

      {/* Collapsible raw data for structured calls */}
      {hasMessages && callData && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <button
            onClick={() => setShowRawData(!showRawData)}
            className="w-full px-6 py-3 flex items-center justify-between text-sm text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <span className="font-medium">Raw Call Data</span>
            {showRawData ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
          {showRawData && (
            <div className="px-6 pb-6">
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs max-h-[400px]">
                {JSON.stringify(callData, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      <ConfirmModal
        title="Delete call"
        description="This will permanently remove this call record."
        isOpen={showDelete}
        isLoading={deleteMutation.isPending}
        onCancel={() => setShowDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
      />

      {/* Evaluate Modal */}
      <AnimatePresence>
        {showEvalModal && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              className="absolute inset-0 bg-black/40 backdrop-blur-sm"
              onClick={() => {
                setShowEvalModal(false)
                setSelectedEvaluator('')
              }}
            />
            <motion.div
              className="relative bg-white rounded-2xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden"
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ duration: 0.2 }}
            >
              <div className="px-6 py-5 border-b border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">Run Evaluation</h2>
                    <p className="text-sm text-gray-500 mt-0.5">
                      Evaluate call <span className="font-mono font-semibold">{callRecording.call_short_id}</span> against an evaluator
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setShowEvalModal(false)
                      setSelectedEvaluator('')
                    }}
                    className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Select Evaluator
                  </label>
                  <select
                    value={selectedEvaluator}
                    onChange={(e) => setSelectedEvaluator(e.target.value)}
                    className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 bg-white"
                  >
                    <option value="">Choose an evaluator...</option>
                    {evaluators.map((evaluator: any) => (
                      <option key={evaluator.id} value={evaluator.id}>
                        {evaluator.evaluator_id} &mdash;{' '}
                        {evaluator.custom_prompt
                          ? `Custom: ${evaluator.name || 'Unnamed'}`
                          : `Agent: ${evaluator.agent_id?.substring(0, 8) || '?'}...`}
                      </option>
                    ))}
                  </select>
                </div>

                {evaluateMutation.isError && (
                  <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-700">
                    {(evaluateMutation.error as any)?.response?.data?.detail || 'Failed to start evaluation'}
                  </div>
                )}
              </div>

              <div className="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex justify-end gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowEvalModal(false)
                    setSelectedEvaluator('')
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => evaluateMutation.mutate(selectedEvaluator)}
                  disabled={!selectedEvaluator || evaluateMutation.isPending}
                  isLoading={evaluateMutation.isPending}
                  leftIcon={!evaluateMutation.isPending ? <Sparkles className="h-4 w-4" /> : undefined}
                >
                  {evaluateMutation.isPending ? 'Starting...' : 'Run Evaluation'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function EventBadge({ event }: { event?: string }) {
  if (!event) return <span className="text-gray-400">&mdash;</span>

  const variants: Record<
    string,
    { label: string; bg: string; text: string; border: string; dot: string }
  > = {
    call_started: {
      label: 'Call Started',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
      dot: 'bg-blue-500',
    },
    call_ended: {
      label: 'Call Ended',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      dot: 'bg-emerald-500',
    },
    call_analyzed: {
      label: 'Call Analyzed',
      bg: 'bg-purple-50',
      text: 'text-purple-700',
      border: 'border-purple-200',
      dot: 'bg-purple-500',
    },
  }

  const variant = variants[event.toLowerCase()] || {
    label: event,
    bg: 'bg-gray-50',
    text: 'text-gray-600',
    border: 'border-gray-200',
    dot: 'bg-gray-400',
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${variant.bg} ${variant.text} ${variant.border}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${variant.dot}`} />
      {variant.label}
    </span>
  )
}

function EndReasonBadge({ reason }: { reason: string }) {
  const colors: Record<string, string> = {
    'customer-hungup': 'bg-amber-50 text-amber-700 border-amber-200',
    'assistant-ended-call': 'bg-blue-50 text-blue-700 border-blue-200',
    voicemail: 'bg-purple-50 text-purple-700 border-purple-200',
    error: 'bg-rose-50 text-rose-700 border-rose-200',
  }

  const colorClass = colors[reason.toLowerCase()] || 'bg-gray-50 text-gray-700 border-gray-200'
  const label = reason
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase())

  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${colorClass}`}
    >
      {label}
    </span>
  )
}

function PlatformBadge({ platform }: { platform?: string }) {
  if (!platform) return <span className="text-gray-400">N/A</span>
  const normalized = platform.toLowerCase()

  const logos: Record<string, string> = {
    retell: '/retellai.png',
    vapi: '/vapi.png',
  }

  const label = normalized.charAt(0).toUpperCase() + normalized.slice(1)
  const logo = logos[normalized]

  return (
    <span className="inline-flex items-center gap-2 text-sm text-gray-700">
      {logo && <img src={logo} alt={label} className="h-5 w-5 object-contain" />}
      <span className="capitalize">{label}</span>
    </span>
  )
}
