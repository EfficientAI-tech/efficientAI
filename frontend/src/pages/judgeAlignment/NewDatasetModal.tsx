import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { X, Upload, FileText } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'

type SourceType = 'transcript' | 'csv'

export default function NewDatasetModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [sourceType, setSourceType] = useState<SourceType>('csv')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [agentId, setAgentId] = useState<string>('')
  const [transcriptLimit, setTranscriptLimit] = useState<number>(100)
  const [error, setError] = useState<string | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const createMutation = useMutation({
    mutationFn: async () => {
      if (sourceType === 'csv') {
        if (!csvFile) throw new Error('Please select a CSV file')
        return apiClient.uploadJudgeDatasetCsv(csvFile, name, description || undefined)
      }
      if (!agentId) throw new Error('Please pick an agent')
      return apiClient.createJudgeDataset({
        name,
        description: description || undefined,
        source_type: 'transcript',
        source_config: { agent_id: agentId, limit: transcriptLimit },
      })
    },
    onSuccess: (dataset) => {
      queryClient.invalidateQueries({ queryKey: ['judge-datasets'] })
      onClose()
      navigate(`/judge-alignment/datasets/${dataset.id}`)
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || e?.message || 'Failed to create dataset')
    },
  })

  const canSubmit = name.trim() && (sourceType !== 'csv' || csvFile)

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div
          className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
          onClick={onClose}
        />

        <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">New judge dataset</h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="p-6 space-y-5 overflow-y-auto">
            <div>
              <label className="text-sm font-medium text-gray-900">Source</label>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <SourceCard
                  active={sourceType === 'csv'}
                  icon={<Upload className="h-5 w-5" />}
                  title="CSV upload"
                  hint="id, input, output[, label]"
                  onClick={() => setSourceType('csv')}
                />
                <SourceCard
                  active={sourceType === 'transcript'}
                  icon={<FileText className="h-5 w-5" />}
                  title="Voice transcripts"
                  hint="From an agent's evaluator results"
                  onClick={() => setSourceType('transcript')}
                />
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-900">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Tone of voice judge calibration"
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400 focus:border-transparent"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-900">
                Description (optional)
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400 focus:border-transparent"
              />
            </div>

            {sourceType === 'csv' && (
              <div>
                <label className="text-sm font-medium text-gray-900">CSV file</label>
                <input
                  type="file"
                  accept=".csv"
                  onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                  className="mt-1 block w-full text-sm text-gray-700 file:mr-3 file:py-2 file:px-4 file:rounded file:border-0 file:bg-yellow-100 file:text-yellow-800 file:font-medium hover:file:bg-yellow-200"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Required columns: <code>id, input, output</code>. Optional:{' '}
                  <code>label</code> (1/fail/true or 0/pass/false).
                </p>
              </div>
            )}

            {sourceType === 'transcript' && (
              <>
                <div>
                  <label className="text-sm font-medium text-gray-900">Agent</label>
                  <select
                    value={agentId}
                    onChange={(e) => setAgentId(e.target.value)}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
                  >
                    <option value="">Select an agent</option>
                    {agents.map((a: any) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    Pulls the most recent evaluator results for this agent that
                    have a transcription attached.
                  </p>
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-900">
                    Max transcripts to import
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={transcriptLimit}
                    onChange={(e) =>
                      setTranscriptLimit(Math.max(1, parseInt(e.target.value, 10) || 100))
                    }
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
                  />
                </div>
              </>
            )}

            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                {error}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-2xl">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => createMutation.mutate()}
              isLoading={createMutation.isPending}
              disabled={!canSubmit}
            >
              Create dataset
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function SourceCard({
  active,
  icon,
  title,
  hint,
  onClick,
}: {
  active: boolean
  icon: React.ReactNode
  title: string
  hint: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left p-3 rounded-lg border transition-all ${
        active
          ? 'border-yellow-400 bg-yellow-50 ring-2 ring-yellow-200'
          : 'border-gray-200 bg-white hover:border-gray-300'
      }`}
    >
      <div className={active ? 'text-yellow-700' : 'text-gray-500'}>{icon}</div>
      <div className="mt-1 text-sm font-medium text-gray-900">{title}</div>
      <div className="text-xs text-gray-500">{hint}</div>
    </button>
  )
}
