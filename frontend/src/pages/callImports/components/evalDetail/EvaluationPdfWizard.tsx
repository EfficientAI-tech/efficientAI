import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Check,
  FileText,
  Grid3x3,
  Loader2,
  Sparkles,
  X,
} from 'lucide-react'
import Button from '../../../../components/Button'
import type { UseQueryResult } from '@tanstack/react-query'
import type {
  CallImportEvaluation,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  EvaluationUserInsightsState,
} from '../../../../types/api'
import {
  MetricClusterGenerationModal,
} from './EvalMetricClustersPanel'
import type { useEvalPdfReports } from '../../hooks/useEvalPdfReports'

type PdfApi = ReturnType<typeof useEvalPdfReports>

export type EvaluationPdfWizardProps = {
  id: string
  evalId: string
  evaluation: CallImportEvaluation
  activeWorkspaceId: string | null | undefined
  pdf: PdfApi
  reportQualityMetrics: { id: string; name: string }[]
  reportInsightMetrics: { id: string; name: string }[]
  userInsightsQuery: UseQueryResult<EvaluationUserInsightsState | null>
  metricClustersQuery: UseQueryResult<EvaluationMetricClustersState | null>
  promptImprovementsQuery: UseQueryResult<EvaluationPromptImprovementsState | null>
  queryClient: ReturnType<typeof useQueryClient>
}

export function EvaluationPdfWizard(props: EvaluationPdfWizardProps) {
  const {
    id,
    evalId,
    evaluation,
    activeWorkspaceId,
    pdf,
    reportQualityMetrics,
    reportInsightMetrics,
    userInsightsQuery,
    metricClustersQuery,
    promptImprovementsQuery,
    queryClient,
  } = props
  const {
    pdfReportOpen,
    pdfClusterModalOpen,
    setPdfClusterModalOpen,
    pdfGenerationError,
    setPdfGenerationError,
    pdfReportLoading,
    pdfWizardStep,
    PDF_WIZARD_STEPS,
    closePdfReportWizard,
    pdfWizardCanReachStep,
    handlePdfWizardStepClick,
    pdfReportType,
    setPdfReportType,
    pdfIncludeWeeklyDelta,
    setPdfIncludeWeeklyDelta,
    baselineCandidatesLoading,
    baselineCandidatesError,
    baselineCandidates,
    selectedBaselineCandidate,
    baselineEvaluationId,
    setBaselineEvaluationId,
    pdfVendorName,
    setPdfVendorName,
    pdfUseCase,
    setPdfUseCase,
    reportBrandingLoading,
    reportHeadingDraft,
    setReportHeadingDraft,
    handleReportHeadingSave,
    internalBrandImageId,
    setInternalBrandImageId,
    externalBrandImageId,
    setExternalBrandImageId,
    internalBrandImages,
    externalBrandImages,
    reportBranding,
    reportLogoUploading,
    handleReportLogoUpload,
    reportLogoDeletingId,
    handleReportImageDelete,
    pdfIncludeAuditSummary,
    setPdfIncludeAuditSummary,
    pdfIncludeQualityPanel,
    setPdfIncludeQualityPanel,
    pdfIncludeUserInsights,
    setPdfIncludeUserInsights,
    pdfIncludeFailureDiagnostics,
    setPdfIncludeFailureDiagnostics,
    pdfIncludePromptImprovements,
    setPdfIncludePromptImprovements,
    pdfIncludeDesignNotes,
    setPdfIncludeDesignNotes,
    pdfIncludeMethodology,
    setPdfIncludeMethodology,
    selectedReportMetricIds,
    setSelectedReportMetricIds,
    selectedReportInsightIds,
    setSelectedReportInsightIds,
    selectedGeneratedUserInsightIds,
    setSelectedGeneratedUserInsightIds,
    handlePdfWizardGenerateUserInsights,
    pdfUserInsightsTriggering,
    userInsightsNeedsGeneration,
    metricClustersNeedsGeneration,
    pdfReportError,
    setPdfReportError,
    handlePdfWizardBack,
    handlePdfWizardNext,
    pdfWizardVendorValid,
    handlePdfPreview,
    pdfReportLoadingAction,
    handlePdfReportSubmit,
    pdfPreviewOpen,
    pdfPreviewUrl,
    pdfPreviewFilename,
    setPdfPreviewUrl,
    setPdfPreviewReportId,
    setPdfPreviewOpen,
    pdfPreviewDownloading,
    handlePdfPreviewDownload,
  } = pdf
  return (
    <>
      {pdfReportOpen &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex-shrink-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-gray-900">
                      Generate PDF report
                    </h2>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Step {pdfWizardStep} of {PDF_WIZARD_STEPS.length}:{' '}
                      {PDF_WIZARD_STEPS[pdfWizardStep - 1]?.label}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={closePdfReportWizard}
                    disabled={pdfReportLoading}
                    className="text-gray-400 hover:text-gray-600 disabled:opacity-50 shrink-0"
                    aria-label="Close PDF report modal"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <ol className="mt-4 flex items-stretch gap-1.5">
                  {PDF_WIZARD_STEPS.map((step) => {
                    const reachable = pdfWizardCanReachStep(step.id)
                    const active = pdfWizardStep === step.id
                    const done = pdfWizardStep > step.id
                    return (
                      <li key={step.id} className="flex-1 min-w-0">
                        <button
                          type="button"
                          onClick={() => handlePdfWizardStepClick(step.id)}
                          disabled={!reachable || pdfReportLoading}
                          className={`w-full rounded-md px-2 py-2 text-left transition-colors disabled:cursor-not-allowed ${
                            active
                              ? 'bg-primary-50 text-primary-800 ring-1 ring-primary-200'
                              : done
                                ? 'text-green-800 hover:bg-green-50'
                                : reachable
                                  ? 'text-gray-700 hover:bg-gray-50'
                                  : 'text-gray-400'
                          }`}
                        >
                          <span className="flex items-center gap-1.5">
                            <span
                              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                                done
                                  ? 'bg-green-100 text-green-700'
                                  : active
                                    ? 'bg-primary-100 text-primary-700'
                                    : 'bg-gray-100 text-gray-500'
                              }`}
                            >
                              {done ? (
                                <Check className="h-3 w-3" aria-hidden />
                              ) : (
                                step.id
                              )}
                            </span>
                            <span className="truncate text-[10px] font-medium leading-tight sm:text-[11px]">
                              {step.label}
                            </span>
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ol>
              </div>

              <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1 min-h-0">
                {pdfWizardStep === 1 && (
                  <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Report type
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <label className="flex items-start gap-2 rounded-md border border-gray-200 p-3 hover:bg-gray-50 cursor-pointer">
                      <input
                        type="radio"
                        name="pdf-report-type"
                        value="external"
                        checked={pdfReportType === 'external'}
                        disabled={pdfReportLoading}
                        onChange={() => setPdfReportType('external')}
                        className="mt-0.5 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>
                        <span className="block text-sm font-medium text-gray-900">
                          External vendor
                        </span>
                        <span className="block text-xs text-gray-500">
                          Vendor-safe report without internal diagnostic IDs.
                        </span>
                      </span>
                    </label>
                    <label className="flex items-start gap-2 rounded-md border border-gray-200 p-3 hover:bg-gray-50 cursor-pointer">
                      <input
                        type="radio"
                        name="pdf-report-type"
                        value="internal"
                        checked={pdfReportType === 'internal'}
                        disabled={pdfReportLoading}
                        onChange={() => setPdfReportType('internal')}
                        className="mt-0.5 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>
                        <span className="block text-sm font-medium text-gray-900">
                          Internal team
                        </span>
                        <span className="block text-xs text-gray-500">
                          Includes diagnostic context for QA review.
                        </span>
                      </span>
                    </label>
                  </div>
                </div>

                <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 space-y-1">
                  <label className="mb-2 flex items-start gap-2 text-sm text-gray-800">
                    <input
                      type="checkbox"
                      checked={pdfIncludeWeeklyDelta}
                      disabled={pdfReportLoading}
                      onChange={(e) => setPdfIncludeWeeklyDelta(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                    />
                    <span>
                      <span className="block font-medium">
                        Include previous-week metric deltas
                      </span>
                      <span className="block text-xs text-gray-500">
                        Compares this report against a prior completed evaluation
                        run in the same workspace.
                      </span>
                    </span>
                  </label>
                  {pdfIncludeWeeklyDelta && (
                    <div className="mt-3 space-y-2 rounded-md border border-gray-200 bg-white p-3">
                      <div className="text-xs font-medium text-gray-800">
                        Previous-week comparison run
                      </div>
                      {baselineCandidatesLoading ? (
                        <div className="flex items-center gap-2 text-xs text-gray-500">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Loading prior evaluation runs...
                        </div>
                      ) : baselineCandidatesError ? (
                        <p className="text-xs text-red-600">{baselineCandidatesError}</p>
                      ) : baselineCandidates.length === 0 ? (
                        <p className="text-xs text-gray-500">
                          No prior completed evaluation run was found in this
                          workspace. Deltas will show as unavailable.
                        </p>
                      ) : (
                        <>
                          {selectedBaselineCandidate && (
                            <p className="text-xs text-gray-600">
                              Using{' '}
                              <span className="font-medium text-gray-900">
                                {selectedBaselineCandidate.name}
                              </span>{' '}
                              from {selectedBaselineCandidate.dataset} (
                              {selectedBaselineCandidate.period_display})
                            </p>
                          )}
                          <label className="block text-xs text-gray-600">
                            Override comparison run
                            <select
                              value={baselineEvaluationId || ''}
                              disabled={pdfReportLoading}
                              onChange={(e) =>
                                setBaselineEvaluationId(e.target.value || null)
                              }
                              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:opacity-50"
                            >
                              {baselineCandidates.map((candidate) => (
                                <option
                                  key={candidate.evaluation_id}
                                  value={candidate.evaluation_id}
                                >
                                  {candidate.name} · {candidate.dataset} ·{' '}
                                  {candidate.period_display}
                                  {candidate.is_default ? ' (default)' : ''}
                                </option>
                              ))}
                            </select>
                          </label>
                        </>
                      )}
                    </div>
                  )}
                </div>
                  </>
                )}

                {pdfWizardStep === 2 && (
                  <>
                <div>
                  <label
                    htmlFor="pdf-vendor-name"
                    className="block text-sm font-medium text-gray-700 mb-1"
                  >
                    Vendor / client name
                  </label>
                  <input
                    id="pdf-vendor-name"
                    type="text"
                    value={pdfVendorName}
                    onChange={(e) => {
                      setPdfVendorName(e.target.value)
                      if (pdfReportError) setPdfReportError(null)
                    }}
                    disabled={pdfReportLoading}
                    placeholder="Vendor or client name"
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500"
                    autoFocus
                  />
                </div>

                <div>
                  <label
                    htmlFor="pdf-use-case"
                    className="block text-sm font-medium text-gray-700 mb-1"
                  >
                    Use case / audit window label
                  </label>
                  <input
                    id="pdf-use-case"
                    type="text"
                    value={pdfUseCase}
                    onChange={(e) => setPdfUseCase(e.target.value)}
                    disabled={pdfReportLoading}
                    placeholder="Inbound · Service"
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <label className="block text-sm font-medium text-gray-700">
                      Header branding
                    </label>
                    {reportBrandingLoading && (
                      <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Loading
                      </span>
                    )}
                  </div>
                  <div className="rounded-md border border-gray-200 p-3 space-y-3">
                    <div>
                      <label
                        htmlFor="pdf-report-heading"
                        className="block text-xs font-medium text-gray-600 mb-1"
                      >
                        Custom heading
                      </label>
                      <div className="flex gap-2">
                        <input
                          id="pdf-report-heading"
                          type="text"
                          value={reportHeadingDraft}
                          onChange={(e) => setReportHeadingDraft(e.target.value)}
                          placeholder="Quality Audit Report"
                          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                          disabled={pdfReportLoading}
                        />
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleReportHeadingSave}
                          disabled={pdfReportLoading}
                        >
                          Save
                        </Button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="rounded border border-gray-200 p-3 space-y-2">
                        <label className="block text-xs font-semibold text-gray-700">
                          Internal brand
                        </label>
                        <select
                          value={internalBrandImageId}
                          onChange={(e) => setInternalBrandImageId(e.target.value)}
                          disabled={pdfReportLoading}
                          className="block w-full rounded-md border border-gray-300 px-2 py-2 text-xs shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        >
                          <option value="">No internal logo</option>
                          {internalBrandImages.map((image) => (
                            <option key={image.id} value={image.id}>
                              {image.filename}
                            </option>
                          ))}
                        </select>
                        <label className="inline-flex items-center justify-center rounded-md border border-gray-300 px-2 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 cursor-pointer">
                          Upload internal
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp,image/svg+xml"
                            className="sr-only"
                            disabled={reportLogoUploading || pdfReportLoading}
                            onChange={(event) =>
                              handleReportLogoUpload(event, 'internal')
                            }
                          />
                        </label>
                      </div>
                      <div className="rounded border border-gray-200 p-3 space-y-2">
                        <label className="block text-xs font-semibold text-gray-700">
                          Vendor brand
                        </label>
                        <select
                          value={externalBrandImageId}
                          onChange={(e) => setExternalBrandImageId(e.target.value)}
                          disabled={pdfReportLoading}
                          className="block w-full rounded-md border border-gray-300 px-2 py-2 text-xs shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        >
                          <option value="">No vendor logo</option>
                          {externalBrandImages.map((image) => (
                            <option key={image.id} value={image.id}>
                              {image.filename}
                            </option>
                          ))}
                        </select>
                        <label className="inline-flex items-center justify-center rounded-md border border-gray-300 px-2 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 cursor-pointer">
                          Upload vendor
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp,image/svg+xml"
                            className="sr-only"
                            disabled={reportLogoUploading || pdfReportLoading}
                            onChange={(event) =>
                              handleReportLogoUpload(event, 'external')
                            }
                          />
                        </label>
                      </div>
                    </div>

                    {reportBranding?.images?.length ? (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {reportBranding.images.map((image) => (
                          <div
                            key={image.id}
                            className="flex items-center justify-between gap-2 rounded border border-gray-200 p-2"
                          >
                            <div className="flex items-center gap-2 min-w-0">
                              {image.data_uri && (
                                <img
                                  src={image.data_uri}
                                  alt={image.filename}
                                  className="h-10 w-12 object-contain rounded border border-gray-200 bg-white"
                                />
                              )}
                              <div className="min-w-0">
                                <p className="text-xs font-medium text-gray-900 truncate">
                                  {image.filename}
                                </p>
                                <p className="text-[11px] text-gray-500">
                                  {image.role} · {Math.ceil(image.size_bytes / 1024)} KB
                                </p>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleReportImageDelete(image.id)}
                              disabled={
                                reportLogoDeletingId !== null || pdfReportLoading
                              }
                              className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                            >
                              {reportLogoDeletingId === image.id
                                ? 'Removing…'
                                : 'Remove'}
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-600">
                        No custom images saved for this workspace.
                      </p>
                    )}
                    <p className="text-xs text-gray-500">
                      PNG, JPG, WEBP, or SVG up to 5 MB each. Saved per workspace.
                    </p>
                  </div>
                </div>
                {pdfReportError && pdfWizardStep === 2 && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">{pdfReportError}</p>
                    </div>
                  </div>
                )}
                  </>
                )}

                {pdfWizardStep === 3 && (
                  <>
                <div className="rounded-md border border-gray-200 p-3 space-y-3">
                  <div>
                    <h3 className="text-sm font-medium text-gray-900">
                      Report customization
                    </h3>
                    <p className="text-xs text-gray-500">
                      Choose sections and the metrics/insights that should appear in
                      this PDF.
                    </p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                    {[
                      ['Audit Summary', pdfIncludeAuditSummary, setPdfIncludeAuditSummary],
                      ['Quality Metric Panel', pdfIncludeQualityPanel, setPdfIncludeQualityPanel],
                      ['User Insights', pdfIncludeUserInsights, setPdfIncludeUserInsights],
                      ...(pdfReportType === 'internal'
                        ? [
                            [
                              'Failure Diagnostics',
                              pdfIncludeFailureDiagnostics,
                              setPdfIncludeFailureDiagnostics,
                            ] as const,
                            [
                              'Prompt Improvements',
                              pdfIncludePromptImprovements,
                              setPdfIncludePromptImprovements,
                            ] as const,
                          ]
                        : []),
                      ['Design Notes', pdfIncludeDesignNotes, setPdfIncludeDesignNotes],
                      ['Methodology', pdfIncludeMethodology, setPdfIncludeMethodology],
                    ].map(([label, checked, setter]) => (
                      <label key={label as string} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={checked as boolean}
                          disabled={pdfReportLoading}
                          onChange={(e) =>
                            (setter as (value: boolean) => void)(e.target.checked)
                          }
                          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        <span>{label as string}</span>
                      </label>
                    ))}
                  </div>
                  {reportQualityMetrics.length ? (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">
                        Quality metrics
                      </p>
                      <div className="max-h-24 overflow-auto rounded border border-gray-100 p-2 space-y-1">
                        {reportQualityMetrics.map((metric) => (
                          <label key={metric.id} className="flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={selectedReportMetricIds.has(metric.id)}
                              onChange={(e) => {
                                setSelectedReportMetricIds((prev) => {
                                  const next = new Set(prev)
                                  if (e.target.checked) next.add(metric.id)
                                  else next.delete(metric.id)
                                  return next
                                })
                              }}
                              className="h-3.5 w-3.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <span>{metric.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {reportInsightMetrics.length && pdfReportType === 'internal' ? (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">
                        User insight metrics (internal)
                      </p>
                      <div className="max-h-24 overflow-auto rounded border border-gray-100 p-2 space-y-1">
                        {reportInsightMetrics.map((metric) => (
                          <label key={metric.id} className="flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={selectedReportInsightIds.has(metric.id)}
                              onChange={(e) => {
                                setSelectedReportInsightIds((prev) => {
                                  const next = new Set(prev)
                                  if (e.target.checked) next.add(metric.id)
                                  else next.delete(metric.id)
                                  return next
                                })
                              }}
                              className="h-3.5 w-3.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <span>{metric.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {pdfReportType === 'external' ? (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">
                        AI user insights (external report)
                      </p>
                      {userInsightsQuery.data?.status === 'running' ? (
                        <p className="text-xs text-amber-700">
                          User insights are still generating. You can continue;
                          the PDF includes them when ready.
                        </p>
                      ) : userInsightsQuery.data?.status === 'completed' &&
                        userInsightsQuery.data.insights.length ? (
                        <div className="max-h-32 overflow-auto rounded border border-gray-100 p-2 space-y-1">
                          {userInsightsQuery.data.insights.map((insight) => (
                            <label
                              key={insight.id}
                              className="flex items-center gap-2 text-xs"
                            >
                              <input
                                type="checkbox"
                                checked={selectedGeneratedUserInsightIds.has(
                                  insight.id,
                                )}
                                disabled={pdfReportLoading}
                                onChange={(e) => {
                                  setSelectedGeneratedUserInsightIds((prev) => {
                                    const next = new Set(prev)
                                    if (e.target.checked) next.add(insight.id)
                                    else next.delete(insight.id)
                                    return next
                                  })
                                }}
                                className="h-3.5 w-3.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                              />
                              <span>{insight.title}</span>
                            </label>
                          ))}
                        </div>
                      ) : userInsightsNeedsGeneration ? (
                        <div className="space-y-2">
                          <p className="text-xs text-gray-500">
                            User insights are not available yet. Start generation
                            here (runs in the background) or continue without
                            section 03 content.
                          </p>
                          <Button
                            variant="outline"
                            size="sm"
                            leftIcon={<Sparkles className="h-3.5 w-3.5" />}
                            onClick={handlePdfWizardGenerateUserInsights}
                            isLoading={pdfUserInsightsTriggering}
                            disabled={
                              pdfUserInsightsTriggering || pdfReportLoading
                            }
                          >
                            Generate user insights
                          </Button>
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500">
                          No user insights are available for this evaluation yet.
                        </p>
                      )}
                    </div>
                  ) : null}
                  {pdfReportType === 'internal' && pdfIncludeFailureDiagnostics ? (
                    (() => {
                      const clusterStatus = metricClustersQuery.data?.status
                      const clusterGroups = metricClustersQuery.data?.groups
                      const clusterProgress = metricClustersQuery.data?.progress
                      const clusterCompleted =
                        clusterProgress?.completed_llm_calls ?? 0
                      const clusterTotal = clusterProgress?.total_llm_calls ?? 0
                      const clusterPct =
                        clusterTotal > 0
                          ? Math.min(
                              100,
                              Math.round((clusterCompleted / clusterTotal) * 100),
                            )
                          : 0
                      return (
                        <div className="rounded-md border border-gray-100 bg-gray-50/80 p-3 space-y-2">
                          <p className="text-xs font-semibold text-gray-700">
                            Failure diagnostics
                          </p>
                          {clusterStatus === 'running' ? (
                            <div className="space-y-2">
                              <p className="text-xs text-amber-700">
                                Clusters are generating in the background. You can
                                continue; the PDF includes them when ready.
                              </p>
                              {clusterTotal > 0 ? (
                                <>
                                  <p className="text-[10px] text-gray-600 tabular-nums">
                                    {clusterCompleted} / {clusterTotal} LLM calls
                                    ({clusterPct}%)
                                  </p>
                                  <div className="h-2 rounded-full bg-amber-100 overflow-hidden">
                                    <div
                                      className="h-full bg-amber-600 transition-all duration-300"
                                      style={{ width: `${clusterPct}%` }}
                                      role="progressbar"
                                      aria-valuenow={clusterCompleted}
                                      aria-valuemin={0}
                                      aria-valuemax={clusterTotal}
                                    />
                                  </div>
                                </>
                              ) : (
                                <div className="h-2 rounded-full bg-amber-100 overflow-hidden">
                                  <div className="h-full w-1/3 bg-amber-400 animate-pulse rounded-full" />
                                </div>
                              )}
                            </div>
                          ) : clusterStatus === 'completed' && clusterGroups?.length ? (
                            <p className="text-xs text-green-700">
                              Includes {clusterGroups.length} cluster group
                              {clusterGroups.length === 1 ? '' : 's'} in the PDF:
                              metric-level failure clusters, counts, examples, and
                              RCA summaries where available.
                            </p>
                          ) : metricClustersNeedsGeneration ? (
                            <div className="space-y-2">
                              <p className="text-xs text-gray-500">
                                Clusters are not available yet. Start generation
                                here (runs in the background) or continue without
                                cluster content in the PDF.
                              </p>
                              <Button
                                variant="outline"
                                size="sm"
                                leftIcon={<Grid3x3 className="h-3.5 w-3.5" />}
                                onClick={() => {
                                  setPdfGenerationError(null)
                                  setPdfClusterModalOpen(true)
                                }}
                                disabled={pdfReportLoading}
                              >
                                Generate clusters
                              </Button>
                            </div>
                          ) : (
                            <p className="text-xs text-gray-500">
                              No cluster groups are available for this evaluation
                              yet.
                            </p>
                          )}
                        </div>
                      )
                    })()
                  ) : null}
                  {pdfReportType === 'internal' && pdfIncludePromptImprovements ? (
                    <div className="rounded-md border border-gray-100 bg-gray-50/80 p-3 space-y-2">
                      <p className="text-xs font-semibold text-gray-700">
                        Prompt improvement recommendations
                      </p>
                      {promptImprovementsQuery.data?.status === 'running' ? (
                        <p className="text-xs text-amber-700">
                          Suggestions are generating in the background.
                        </p>
                      ) : promptImprovementsQuery.data?.status === 'completed' &&
                        promptImprovementsQuery.data.suggestions.length ? (
                        <p className="text-xs text-gray-600">
                          Top{' '}
                          {Math.min(5, promptImprovementsQuery.data.suggestions.length)}{' '}
                          recommended change
                          {Math.min(5, promptImprovementsQuery.data.suggestions.length) === 1
                            ? ''
                            : 's'}{' '}
                          for{' '}
                          {promptImprovementsQuery.data.imported_agent_name ||
                            'the mapped imported agent'}{' '}
                          will be included, with before/after prompt text for edits and
                          addition blocks for new content.
                        </p>
                      ) : (
                        <p className="text-xs text-gray-500">
                          Generate suggestions in Visualizations → Prompt / Agent
                          Improvements before including this section.
                        </p>
                      )}
                    </div>
                  ) : null}
                </div>

                {(pdfGenerationError || pdfReportError) && pdfWizardStep === 3 && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">
                        {pdfGenerationError || pdfReportError}
                      </p>
                    </div>
                  </div>
                )}
                  </>
                )}

                {pdfWizardStep === 4 && (
                  <>
                <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3 text-sm text-gray-800">
                  <h3 className="font-medium text-gray-900">Review your report</h3>
                  <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
                    <div>
                      <dt className="text-gray-500">Report type</dt>
                      <dd className="font-medium capitalize">{pdfReportType}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Vendor</dt>
                      <dd className="font-medium">{pdfVendorName.trim() || '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Use case</dt>
                      <dd className="font-medium">
                        {pdfUseCase.trim() || '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Previous-week deltas</dt>
                      <dd className="font-medium">
                        {pdfIncludeWeeklyDelta ? 'Yes' : 'No'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Quality metrics</dt>
                      <dd className="font-medium">
                        {selectedReportMetricIds.size} selected
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Sections</dt>
                      <dd className="font-medium">
                        {[
                          pdfIncludeAuditSummary && 'Audit',
                          pdfIncludeQualityPanel && 'Quality',
                          pdfIncludeUserInsights && 'Insights',
                          pdfReportType === 'internal' &&
                            pdfIncludeFailureDiagnostics &&
                            'Diagnostics',
                          pdfIncludeDesignNotes && 'Design',
                          pdfIncludeMethodology && 'Methodology',
                        ]
                          .filter(Boolean)
                          .join(', ') || 'None'}
                      </dd>
                    </div>
                  </dl>
                  <p className="text-xs text-gray-600">
                    Preview the PDF before downloading. Metric panels include
                    evaluated counts, flagged rate, passing rate, and value
                    distributions. CSV and Excel exports remain in the Download
                    menu.
                  </p>
                </div>

                {pdfReportError && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">{pdfReportError}</p>
                    </div>
                  </div>
                )}
                  </>
                )}
              </div>

              <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between gap-3 flex-shrink-0">
                <Button
                  variant="outline"
                  onClick={closePdfReportWizard}
                  disabled={pdfReportLoading}
                >
                  Cancel
                </Button>
                <div className="flex items-center gap-3">
                  {pdfWizardStep > 1 && (
                    <Button
                      variant="outline"
                      onClick={handlePdfWizardBack}
                      disabled={pdfReportLoading}
                    >
                      Back
                    </Button>
                  )}
                  {pdfWizardStep < 4 ? (
                    <Button
                      variant="primary"
                      onClick={handlePdfWizardNext}
                      disabled={pdfReportLoading}
                    >
                      Next
                    </Button>
                  ) : (
                    <>
                      <Button
                        variant="outline"
                        onClick={handlePdfPreview}
                        isLoading={pdfReportLoadingAction === 'preview'}
                        disabled={pdfReportLoading || !pdfWizardVendorValid}
                      >
                        Preview
                      </Button>
                      <Button
                        variant="primary"
                        leftIcon={<FileText className="h-4 w-4" />}
                        onClick={handlePdfReportSubmit}
                        isLoading={pdfReportLoadingAction === 'download'}
                        disabled={pdfReportLoading || !pdfWizardVendorValid}
                      >
                        Download PDF
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {id && evalId ? (
        <MetricClusterGenerationModal
          open={pdfClusterModalOpen}
          onClose={() => setPdfClusterModalOpen(false)}
          callImportId={id}
          evaluationId={evalId}
          defaultProvider={evaluation?.llm_provider ?? ''}
          defaultModel={evaluation?.llm_model ?? ''}
          state={metricClustersQuery.data ?? null}
          overlayZIndexClass="z-[70]"
          onGenerated={() => {
            queryClient.invalidateQueries({
              queryKey: [
                'call-import-evaluation-metric-clusters',
                activeWorkspaceId,
                id,
                evalId,
              ],
            })
            setPdfClusterModalOpen(false)
          }}
          onError={setPdfGenerationError}
        />
      ) : null}

      {pdfPreviewOpen &&
        pdfPreviewUrl &&
        createPortal(
          <div className="fixed inset-0 z-[60] flex flex-col bg-black/50">
            <div className="flex items-center justify-between gap-3 px-4 py-3 bg-white border-b border-gray-200 shadow-sm">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  PDF preview — {pdfPreviewFilename}
                </p>
                <p className="text-xs text-gray-500">
                  Review the report before downloading. Close to return to
                  configuration.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  variant="outline"
                  onClick={handlePdfPreviewDownload}
                  isLoading={pdfPreviewDownloading}
                  disabled={pdfPreviewDownloading}
                >
                  Download
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    if (pdfPreviewUrl?.startsWith('blob:')) {
                      window.URL.revokeObjectURL(pdfPreviewUrl)
                    }
                    setPdfPreviewUrl(null)
                    setPdfPreviewReportId(null)
                    setPdfPreviewOpen(false)
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
            <iframe
              title="PDF report preview"
              src={pdfPreviewUrl}
              className="flex-1 w-full bg-gray-100 border-0"
            />
          </div>,
          document.body,
        )}

    </>
  )
}
