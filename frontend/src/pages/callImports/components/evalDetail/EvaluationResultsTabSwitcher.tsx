import { BarChart3, Table, Workflow } from 'lucide-react'

export type EvaluationResultsTab = 'table' | 'visualizations' | 'flow'

type Props = {
  resultsTab: EvaluationResultsTab
  setResultsTab: (t: EvaluationResultsTab) => void
}

export function EvaluationResultsTabSwitcher({ resultsTab, setResultsTab }: Props) {
  return (
    <div
      className="inline-flex rounded-md border border-amber-300 bg-amber-50/80 p-0.5 shrink-0"
      role="tablist"
      aria-label="Row results view"
    >
      <button
        type="button"
        role="tab"
        aria-selected={resultsTab === 'table'}
        onClick={() => setResultsTab('table')}
        className={`inline-flex items-center rounded px-2.5 py-1 text-[13px] font-medium transition ${
          resultsTab === 'table'
            ? 'bg-white text-amber-950 shadow-sm'
            : 'text-gray-600 hover:text-gray-900'
        }`}
      >
        <Table className="mr-1 h-3.5 w-3.5 shrink-0" />
        Table
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={resultsTab === 'visualizations'}
        onClick={() => setResultsTab('visualizations')}
        className={`inline-flex items-center rounded px-2.5 py-1 text-[13px] font-medium transition ${
          resultsTab === 'visualizations'
            ? 'bg-white text-amber-950 shadow-sm'
            : 'text-gray-600 hover:text-gray-900'
        }`}
      >
        <BarChart3 className="mr-1 h-3.5 w-3.5 shrink-0" />
        Visualizations
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={resultsTab === 'flow'}
        onClick={() => setResultsTab('flow')}
        className={`inline-flex items-center rounded px-2.5 py-1 text-[13px] font-medium transition ${
          resultsTab === 'flow'
            ? 'bg-white text-amber-950 shadow-sm'
            : 'text-gray-600 hover:text-gray-900'
        }`}
      >
        <Workflow className="mr-1 h-3.5 w-3.5 shrink-0" />
        Flow
      </button>
    </div>
  )
}
