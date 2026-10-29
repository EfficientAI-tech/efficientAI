import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  ChevronDown,
  Download,
  FileText,
  RefreshCw,
  RotateCw,
  Trash2,
  XCircle,
  BarChart3,
  Table,
  Workflow,
} from 'lucide-react'
import Button from '../../../../components/Button'
import { itemsOf } from '../../../../lib/safeData'
import type { CallImportEvaluation, CallImportEvaluationPdfReportListItem } from '../../../../types/api'
import { exportReadyHint } from './evalDetailExport'
import type { useEvalPdfReports } from '../../hooks/useEvalPdfReports'
import type { useEvalRetryMutations } from '../../hooks/useEvalRetryMutations'

type PdfApi = ReturnType<typeof useEvalPdfReports>
type RetryApi = ReturnType<typeof useEvalRetryMutations>

export type EvaluationDetailHeaderProps = {
  id: string
  evalId: string
  evaluation: CallImportEvaluation
  rowsQuery: { data?: { items?: unknown[]; total?: number } | undefined }
  bulkOperationActive: boolean
  bulkOperation: string | null
  cancelEvaluationMutation: {
    isPending: boolean
    mutate: () => void
  }
  retry: RetryApi
  pdf: PdfApi
  downloadMenuOpen: boolean
  setDownloadMenuOpen: (v: boolean | ((p: boolean) => boolean)) => void
  downloadMenuRef: React.RefObject<HTMLDivElement>
  exportPreparing: boolean
  exportParts: { part: number; download_url?: string | null }[]
  handleExport: (format: 'csv' | 'xlsx') => void
  setDeleteEvalOpen: (v: boolean) => void
  resultsTab: 'table' | 'visualizations' | 'flow'
  setResultsTab: (t: 'table' | 'visualizations' | 'flow') => void
}

export function EvaluationDetailHeader(props: EvaluationDetailHeaderProps) {
  const {
    id,
    evaluation,
    rowsQuery,
    bulkOperationActive,
    bulkOperation,
    cancelEvaluationMutation,
    retry,
    pdf,
    downloadMenuOpen,
    setDownloadMenuOpen,
    downloadMenuRef,
    exportPreparing,
    exportParts,
    handleExport,
    setDeleteEvalOpen,
    resultsTab,
    setResultsTab,
  } = props
  const {
    retryAllFailedMutation,
    setRetryError,
    setRetryConfirmOpen,
    rerunMetricsMutation,
    setRerunError,
    setRerunMetricsOpen,
  } = retry
  const {
    pdfReportMenuOpen,
    setPdfReportMenuOpen,
    pdfReportMenuRef,
    pdfReportsQuery,
    setPdfReportError,
    setPdfGenerationError,
    setPdfWizardStep,
    setPdfReportOpen,
    openStoredPdfPreview,
  } = pdf
  return (
    <>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Link
          to={`/call-imports/${id}`}
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to call import
        </Link>
        <div className="flex items-center gap-2">
          {(evaluation.status === 'pending' ||
            evaluation.status === 'running') && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<XCircle className="h-4 w-4" />}
              onClick={() => {
                if (
                  cancelEvaluationMutation.isPending ||
                  bulkOperationActive
                ) {
                  return
                }
                cancelEvaluationMutation.mutate()
              }}
              isLoading={
                cancelEvaluationMutation.isPending || bulkOperation === 'abort'
              }
              disabled={
                bulkOperationActive || cancelEvaluationMutation.isPending
              }
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 border-amber-200"
              title="Abort every in-flight or queued row in this run"
            >
              Abort run
            </Button>
          )}
          {evaluation.failed_rows > 0 && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<RotateCw className="h-4 w-4" />}
              onClick={() => {
                if (bulkOperationActive || retryAllFailedMutation.isPending) {
                  return
                }
                setRetryError(null)
                setRetryConfirmOpen(true)
              }}
              isLoading={
                retryAllFailedMutation.isPending || bulkOperation === 'retry'
              }
              disabled={
                bulkOperationActive || retryAllFailedMutation.isPending
              }
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 border-amber-200"
              title={`Re-run evaluation on ${evaluation.failed_rows} failed row${
                evaluation.failed_rows === 1 ? '' : 's'
              }`}
            >
              Retry failed ({evaluation.failed_rows})
            </Button>
          )}
          {(evaluation.metrics?.length ?? 0) > 0 && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<RefreshCw className="h-4 w-4" />}
              onClick={() => {
                if (bulkOperationActive || rerunMetricsMutation.isPending) {
                  return
                }
                setRerunError(null)
                setRerunMetricsOpen(true)
              }}
              isLoading={
                rerunMetricsMutation.isPending || bulkOperation === 'retry'
              }
              disabled={bulkOperationActive || rerunMetricsMutation.isPending}
              title="Re-score selected metrics across every row in this run, merging into existing scores."
            >
              Re-run metrics
            </Button>
          )}
          <div className="relative" ref={pdfReportMenuRef}>
            <Button
              variant="outline"
              size="sm"
              leftIcon={<FileText className="h-4 w-4" />}
              rightIcon={
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${
                    pdfReportMenuOpen ? 'rotate-180' : ''
                  }`}
                />
              }
              onClick={() => setPdfReportMenuOpen((prev) => !prev)}
              disabled={(evaluation?.total_rows ?? 0) < 1}
            >
              PDF report
            </Button>
            {pdfReportMenuOpen && (
              <div
                className="absolute right-0 z-20 mt-1 w-80 flex flex-col max-h-[min(28rem,70vh)] bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden"
                role="menu"
              >
                <div className="p-2 border-b border-gray-100 shrink-0">
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full flex items-center justify-center gap-1.5 rounded-md border border-amber-500 bg-white px-2.5 py-1.5 text-xs font-semibold text-amber-900 hover:border-amber-600 hover:bg-amber-50/50 transition-colors"
                    onClick={() => {
                      setPdfReportMenuOpen(false)
                      setPdfReportError(null)
                      setPdfGenerationError(null)
                      setPdfWizardStep(1)
                      setPdfReportOpen(true)
                    }}
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    Generate new PDF
                  </button>
                </div>
                <div className="px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide border-b border-gray-100 shrink-0 bg-white">
                  History
                </div>
                <div
                  className="overflow-y-auto overscroll-y-contain min-h-0 flex-1 [scrollbar-gutter:stable]"
                  role="group"
                  aria-label="Stored PDF reports"
                >
                  {pdfReportsQuery.isLoading ? (
                    <p className="px-3 py-3 text-sm text-gray-500">Loading…</p>
                  ) : (pdfReportsQuery.data?.items?.length ?? 0) === 0 ? (
                    <p className="px-3 py-3 text-sm text-gray-500">
                      No stored reports yet.
                    </p>
                  ) : (
                    <ul className="py-1">
                      {itemsOf<CallImportEvaluationPdfReportListItem>(pdfReportsQuery.data).map((item) => (
                        <li key={item.id}>
                          <button
                            type="button"
                            className="w-full px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 focus:outline-none focus-visible:bg-gray-50 border-b border-gray-50 last:border-b-0"
                            role="menuitem"
                            onClick={() => openStoredPdfPreview(item.id)}
                          >
                            <span className="font-medium text-gray-900 block truncate">
                              {item.vendor_name} · {item.report_type}
                            </span>
                            <span className="text-xs text-gray-500 block truncate mt-0.5">
                              {new Date(item.created_at).toLocaleString()}
                              {item.created_by ? ` · ${item.created_by}` : ''}
                            </span>
                            {item.config_summary ? (
                              <span className="text-xs text-gray-400 block truncate mt-0.5">
                                {item.config_summary}
                              </span>
                            ) : null}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className="relative" ref={downloadMenuRef}>
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Download className="h-4 w-4" />}
              rightIcon={
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${
                    downloadMenuOpen ? 'rotate-180' : ''
                  }`}
                />
              }
              onClick={() => setDownloadMenuOpen((prev) => !prev)}
              disabled={!rowsQuery.data?.items?.length || exportPreparing}
              title={
                exportPreparing
                  ? `Preparing download. ${exportReadyHint(evaluation?.total_rows ?? 0)}`
                  : exportReadyHint(evaluation?.total_rows ?? 0)
              }
            >
              {exportPreparing ? 'Preparing download…' : 'Download'}
            </Button>
            {downloadMenuOpen && (
              <div
                className="absolute right-0 z-20 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden"
                role="menu"
              >
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                  title={exportReadyHint(evaluation?.total_rows ?? 0)}
                  onClick={() => handleExport('csv')}
                  role="menuitem"
                >
                  Download as CSV
                </button>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:text-gray-400"
                  onClick={() => handleExport('xlsx')}
                  disabled={(evaluation?.total_rows ?? 0) > 1048576}
                  title={
                    (evaluation?.total_rows ?? 0) > 1048576
                      ? 'Excel cannot open a sheet this long. Download the CSV instead.'
                      : exportReadyHint(evaluation?.total_rows ?? 0)
                  }
                  role="menuitem"
                >
                  Download as Excel
                </button>
              </div>
            )}
            {exportParts.length > 1 && !downloadMenuOpen && (
              <div className="absolute right-0 z-20 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">
                {exportParts.map((part) => (
                  <a
                    key={part.part}
                    href={part.download_url || undefined}
                    className="block px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                  >
                    Part {part.part}
                  </a>
                ))}
              </div>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Trash2 className="h-4 w-4" />}
            onClick={() => setDeleteEvalOpen(true)}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            Delete run
          </Button>
        </div>
      </div>
      <div
        className="inline-flex rounded-md border border-amber-300 bg-amber-50/80 p-0.5 mt-4"
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
    </>
  )
}
