import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, Tag, Play, Sparkles } from 'lucide-react'
import { apiClient } from '../../lib/api'
import LabelingView from './LabelingView'
import EvaluateJudge from './EvaluateJudge'
import OptimizeJudge from './OptimizeJudge'

type Tab = 'label' | 'evaluate' | 'optimize'

export default function JudgeDatasetDetail() {
  const { datasetId = '' } = useParams<{ datasetId: string }>()
  const [tab, setTab] = useState<Tab>('label')

  const { data: dataset, isLoading } = useQuery({
    queryKey: ['judge-dataset', datasetId],
    queryFn: () => apiClient.getJudgeDataset(datasetId),
    enabled: !!datasetId,
    refetchInterval: 5000,
  })

  const { data: settings } = useQuery({
    queryKey: ['judge-alignment', 'settings'],
    queryFn: () => apiClient.getJudgeAlignmentSettings(),
  })

  // Auto-advance tab when thresholds unlock new actions, so first-time users
  // see the Evaluate / Optimize step appear without hunting for it.
  useEffect(() => {
    if (!dataset || !settings) return
    if (tab === 'label' && dataset.labeled_samples >= settings.min_labels_to_evaluate) {
      // Stay on labeling unless user explicitly switches; just enable the tab.
    }
  }, [dataset, settings, tab])

  if (isLoading || !dataset) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
      </div>
    )
  }

  const minEval = settings?.min_labels_to_evaluate ?? 20
  const minOpt = settings?.min_labels_to_optimize ?? 50
  const evalUnlocked = dataset.labeled_samples >= minEval
  const optUnlocked = dataset.labeled_samples >= minOpt

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/judge-alignment"
          className="inline-flex items-center text-sm text-gray-600 hover:text-gray-900"
        >
          <ChevronLeft className="h-4 w-4 mr-1" />
          All judge datasets
        </Link>
        <div className="mt-2 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{dataset.name}</h1>
            {dataset.description && (
              <p className="mt-1 text-sm text-gray-600">{dataset.description}</p>
            )}
            <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
              <span className="inline-flex items-center gap-1">
                <Tag className="h-3 w-3" />
                {dataset.source_type}
              </span>
              <span>
                {dataset.labeled_samples} / {dataset.total_samples} labeled
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          <TabBtn active={tab === 'label'} onClick={() => setTab('label')}>
            <Tag className="h-4 w-4" /> Label
          </TabBtn>
          <TabBtn
            active={tab === 'evaluate'}
            onClick={() => evalUnlocked && setTab('evaluate')}
            disabled={!evalUnlocked}
            hint={
              evalUnlocked
                ? undefined
                : `Label ${minEval - dataset.labeled_samples} more sample(s) to unlock`
            }
          >
            <Play className="h-4 w-4" /> Evaluate
          </TabBtn>
          <TabBtn
            active={tab === 'optimize'}
            onClick={() => optUnlocked && setTab('optimize')}
            disabled={!optUnlocked}
            hint={
              optUnlocked
                ? undefined
                : `Label ${minOpt - dataset.labeled_samples} more sample(s) to unlock`
            }
          >
            <Sparkles className="h-4 w-4" /> Optimize
          </TabBtn>
        </nav>
      </div>

      {tab === 'label' && (
        <LabelingView
          datasetId={datasetId}
          labeledCount={dataset.labeled_samples}
          totalCount={dataset.total_samples}
          minEval={minEval}
          minOpt={minOpt}
          inputField={dataset.input_field}
          outputField={dataset.output_field}
        />
      )}
      {tab === 'evaluate' && <EvaluateJudge datasetId={datasetId} />}
      {tab === 'optimize' && <OptimizeJudge datasetId={datasetId} />}
    </div>
  )
}

function TabBtn({
  active,
  onClick,
  disabled,
  hint,
  children,
}: {
  active: boolean
  onClick: () => void
  disabled?: boolean
  hint?: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={hint}
      className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium flex items-center gap-2 ${
        active
          ? 'border-yellow-500 text-yellow-700'
          : disabled
          ? 'border-transparent text-gray-300 cursor-not-allowed'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
      }`}
    >
      {children}
    </button>
  )
}
