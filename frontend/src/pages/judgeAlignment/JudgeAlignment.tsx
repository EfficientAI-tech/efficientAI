import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Plus, Trash2, Settings, Database, FileText, Upload, Sparkles } from 'lucide-react'
import { format } from 'date-fns'
import { apiClient } from '../../lib/api'
import type { JudgeDataset } from '../../lib/api'
import Button from '../../components/Button'
import NewDatasetModal from './NewDatasetModal'
import SettingsPanel from './SettingsPanel'

export default function JudgeAlignment() {
  const queryClient = useQueryClient()
  const [showNewModal, setShowNewModal] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ['judge-datasets'],
    queryFn: () => apiClient.listJudgeDatasets(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteJudgeDataset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['judge-datasets'] }),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Judge Alignment</h1>
          <p className="mt-2 text-sm text-gray-600 max-w-2xl">
            Calibrate your LLM-as-a-judge evaluators against human-labeled data.
            Upload a CSV, label voice transcripts, or wrap an existing metric;
            measure precision / recall / F1 / Cohen's kappa, then optimise the
            judge prompt with GEPA.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            leftIcon={<Settings className="h-4 w-4" />}
            onClick={() => setShowSettings(true)}
          >
            Settings
          </Button>
          <Button
            variant="primary"
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={() => setShowNewModal(true)}
          >
            New dataset
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
        </div>
      ) : datasets.length === 0 ? (
        <EmptyState onCreate={() => setShowNewModal(true)} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {datasets.map((d: JudgeDataset) => (
            <DatasetCard
              key={d.id}
              dataset={d}
              onDelete={() => {
                if (window.confirm(`Delete dataset "${d.name}"?`)) {
                  deleteMutation.mutate(d.id)
                }
              }}
            />
          ))}
        </div>
      )}

      {showNewModal && (
        <NewDatasetModal onClose={() => setShowNewModal(false)} />
      )}
      {showSettings && (
        <SettingsPanel onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}

function sourceIcon(sourceType: JudgeDataset['source_type']) {
  switch (sourceType) {
    case 'transcript':
      return <FileText className="h-4 w-4 text-blue-600" />
    case 'metric_output':
      return <Database className="h-4 w-4 text-purple-600" />
    case 'csv':
      return <Upload className="h-4 w-4 text-green-600" />
  }
}

function sourceLabel(sourceType: JudgeDataset['source_type']) {
  switch (sourceType) {
    case 'transcript':
      return 'Voice transcript'
    case 'metric_output':
      return 'Metric output'
    case 'csv':
      return 'CSV upload'
  }
}

function DatasetCard({
  dataset,
  onDelete,
}: {
  dataset: JudgeDataset
  onDelete: () => void
}) {
  const labelPct =
    dataset.total_samples > 0
      ? Math.round((dataset.labeled_samples / dataset.total_samples) * 100)
      : 0

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm hover:shadow-md transition-shadow flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/judge-alignment/datasets/${dataset.id}`}
          className="flex-1 min-w-0"
        >
          <div className="flex items-center gap-2 mb-1">
            {sourceIcon(dataset.source_type)}
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              {sourceLabel(dataset.source_type)}
            </span>
          </div>
          <h3 className="text-lg font-semibold text-gray-900 truncate">
            {dataset.name}
          </h3>
          {dataset.description && (
            <p className="mt-1 text-sm text-gray-600 line-clamp-2">
              {dataset.description}
            </p>
          )}
        </Link>
        <button
          onClick={onDelete}
          className="text-gray-400 hover:text-red-600 transition-colors p-1"
          title="Delete dataset"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-4 space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-600">Labeled</span>
          <span className="font-medium text-gray-900">
            {dataset.labeled_samples} / {dataset.total_samples}
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-1.5">
          <div
            className="bg-yellow-400 h-1.5 rounded-full transition-all"
            style={{ width: `${labelPct}%` }}
          />
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
        <span>
          {dataset.created_at
            ? format(new Date(dataset.created_at), 'MMM d, yyyy')
            : ''}
        </span>
        <Link
          to={`/judge-alignment/datasets/${dataset.id}`}
          className="text-yellow-700 hover:text-yellow-900 font-medium flex items-center gap-1"
        >
          Open <Sparkles className="h-3 w-3" />
        </Link>
      </div>
    </div>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="bg-white border-2 border-dashed border-gray-300 rounded-lg p-12 text-center">
      <Sparkles className="mx-auto h-12 w-12 text-gray-400" />
      <h3 className="mt-2 text-sm font-medium text-gray-900">
        No judge datasets yet
      </h3>
      <p className="mt-1 text-sm text-gray-500 max-w-md mx-auto">
        Get started by importing voice transcripts, wrapping an existing metric,
        or uploading an AlignEval-style CSV.
      </p>
      <div className="mt-6">
        <Button
          variant="primary"
          leftIcon={<Plus className="h-4 w-4" />}
          onClick={onCreate}
        >
          Create your first dataset
        </Button>
      </div>
    </div>
  )
}
