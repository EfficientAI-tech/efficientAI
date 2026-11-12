import { type ChangeEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, type ReportBranding } from '../../../lib/api'
import { getApiErrorMessage } from '../../../lib/apiErrors'
import { downloadBlob } from '../../../lib/download'
import type {
  CallImportEvaluationBaselineCandidate,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  EvaluationUserInsightsState,
} from '../../../types/api'
import { useToast } from '../../../hooks/useToast'

type DisplayMetric = {
  id: string
  name: string
  metricCategory: string
}

export type UseEvalPdfReportsArgs = {
  callImportId: string | undefined
  evaluationId: string | undefined
  activeWorkspaceId: string | null | undefined
  evalId: string | undefined
  pdfReportOpen: boolean
  setPdfReportOpen: (open: boolean) => void
  resultsTab: 'table' | 'visualizations' | 'flow'
  reportQualityMetrics: DisplayMetric[]
  reportInsightMetrics: DisplayMetric[]
  userInsightsQuery: {
    data?: EvaluationUserInsightsState | null
    refetch: () => Promise<unknown>
  }
  metricClustersQuery: {
    data?: EvaluationMetricClustersState | null
  }
  promptImprovementsQuery: {
    data?: EvaluationPromptImprovementsState | null
  }
}

export function useEvalPdfReports({
  callImportId,
  activeWorkspaceId,
  evalId,
  pdfReportOpen,
  setPdfReportOpen,
  reportQualityMetrics,
  reportInsightMetrics,
  userInsightsQuery,
  metricClustersQuery,
}: UseEvalPdfReportsArgs) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const id = callImportId
  const [pdfReportMenuOpen, setPdfReportMenuOpen] = useState(false)
  const pdfReportMenuRef = useRef<HTMLDivElement>(null)
  const [pdfWizardStep, setPdfWizardStep] = useState(1)
  const [pdfUserInsightsTriggering, setPdfUserInsightsTriggering] =
    useState(false)
  const [pdfClusterModalOpen, setPdfClusterModalOpen] = useState(false)
  const [pdfGenerationError, setPdfGenerationError] = useState<string | null>(
    null,
  )
  const [pdfVendorName, setPdfVendorName] = useState('')
  const [pdfReportType, setPdfReportType] = useState<'external' | 'internal'>(
    'external',
  )
  const [pdfIncludeWeeklyDelta, setPdfIncludeWeeklyDelta] = useState(false)
  const [baselineCandidates, setBaselineCandidates] = useState<
    CallImportEvaluationBaselineCandidate[]
  >([])
  const [baselineEvaluationId, setBaselineEvaluationId] = useState<string | null>(
    null,
  )
  const [baselineCandidatesLoading, setBaselineCandidatesLoading] =
    useState(false)
  const [baselineCandidatesError, setBaselineCandidatesError] = useState<
    string | null
  >(null)
  const [pdfUseCase, setPdfUseCase] = useState('')
  const [pdfIncludeAuditSummary, setPdfIncludeAuditSummary] = useState(true)
  const [pdfIncludeQualityPanel, setPdfIncludeQualityPanel] = useState(true)
  const [pdfIncludeUserInsights, setPdfIncludeUserInsights] = useState(true)
  const [pdfIncludeDesignNotes, setPdfIncludeDesignNotes] = useState(true)
  const [pdfIncludeMethodology, setPdfIncludeMethodology] = useState(true)
  const [pdfIncludeFailureDiagnostics, setPdfIncludeFailureDiagnostics] =
    useState(true)
  const [pdfIncludePromptImprovements, setPdfIncludePromptImprovements] =
    useState(true)
  const [pdfPreviewOpen, setPdfPreviewOpen] = useState(false)
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null)
  const [pdfPreviewFilename, setPdfPreviewFilename] = useState('')
  const [pdfPreviewReportId, setPdfPreviewReportId] = useState<string | null>(
    null,
  )
  const [pdfPreviewDownloading, setPdfPreviewDownloading] = useState(false)
  const [selectedReportMetricIds, setSelectedReportMetricIds] = useState<Set<string>>(
    new Set(),
  )
  const [selectedReportInsightIds, setSelectedReportInsightIds] = useState<Set<string>>(
    new Set(),
  )
  const [selectedGeneratedUserInsightIds, setSelectedGeneratedUserInsightIds] =
    useState<Set<string>>(new Set())
  const [pdfReportError, setPdfReportError] = useState<string | null>(null)
  const [pdfReportLoadingAction, setPdfReportLoadingAction] = useState<
    null | 'preview' | 'download'
  >(null)
  const pdfReportLoading = pdfReportLoadingAction !== null
  const [reportBranding, setReportBranding] = useState<ReportBranding | null>(
    null,
  )
  const [reportHeadingDraft, setReportHeadingDraft] = useState('')
  const [internalBrandImageId, setInternalBrandImageId] = useState('')
  const [externalBrandImageId, setExternalBrandImageId] = useState('')
  const [reportBrandingLoading, setReportBrandingLoading] = useState(false)
  const [reportLogoUploading, setReportLogoUploading] = useState(false)
  const [reportLogoDeletingId, setReportLogoDeletingId] = useState<string | null>(
    null,
  )
  const pdfReportsQuery = useQuery({
    queryKey: ['call-import-evaluation-pdf-reports', activeWorkspaceId, id, evalId],
    queryFn: () => apiClient.callImports.listCallImportEvaluationPdfReports(id!, evalId!),
    enabled: pdfReportMenuOpen && !!id && !!evalId,
  })
  useEffect(() => {
    if (!pdfReportOpen) return
    setSelectedReportMetricIds(new Set(reportQualityMetrics.map((metric) => metric.id)))
    setSelectedReportInsightIds(new Set(reportInsightMetrics.map((metric) => metric.id)))
    const generated = userInsightsQuery.data?.insights ?? []
    if (generated.length) {
      setSelectedGeneratedUserInsightIds(new Set(generated.map((item) => item.id)))
    }
  }, [
    pdfReportOpen,
    reportQualityMetrics,
    reportInsightMetrics,
    userInsightsQuery.data?.insights,
  ])
  const internalBrandImages = useMemo(
    () =>
      (reportBranding?.images || []).filter(
        (image) => image.role === 'internal' || image.role === 'generic',
      ),
    [reportBranding?.images],
  )
  const externalBrandImages = useMemo(
    () =>
      (reportBranding?.images || []).filter(
        (image) => image.role === 'external' || image.role === 'generic',
      ),
    [reportBranding?.images],
  )

  const syncSelectedBrandImages = (branding: ReportBranding) => {
    const internalDefault =
      branding.images.find((image) => image.role === 'internal') ||
      branding.images.find((image) => image.role === 'generic')
    const externalDefault =
      branding.images.find((image) => image.role === 'external') ||
      branding.images.find((image) => image.role === 'generic')
    setInternalBrandImageId((current) =>
      current && branding.images.some((image) => image.id === current)
        ? current
        : internalDefault?.id || '',
    )
    setExternalBrandImageId((current) =>
      current && branding.images.some((image) => image.id === current)
        ? current
        : externalDefault?.id || '',
    )
  }

  const generatePdfReportBlob = async (vendorName: string) => {
    if ((reportBranding?.heading || '') !== reportHeadingDraft.trim()) {
      const branding = await apiClient.updateReportBranding({
        heading: reportHeadingDraft.trim() || null,
      })
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
    }
    return apiClient.callImports.generateCallImportEvaluationPdfReport(
      id!,
      evalId!,
      vendorName,
      pdfReportType,
      pdfIncludeWeeklyDelta,
      {
        internalBrandImageId: internalBrandImageId || null,
        externalBrandImageId: externalBrandImageId || null,
        useCase: pdfUseCase.trim() || null,
        baselineEvaluationId: pdfIncludeWeeklyDelta ? baselineEvaluationId : null,
        platformBaseUrl:
          typeof window !== 'undefined' ? window.location.origin : null,
        reportConfig: {
          use_case: pdfUseCase.trim() || null,
          sections: {
            audit_summary: pdfIncludeAuditSummary,
            quality_panel: pdfIncludeQualityPanel,
            user_insights: pdfIncludeUserInsights,
            failure_diagnostics: pdfIncludeFailureDiagnostics,
            prompt_improvements: pdfIncludePromptImprovements,
            design_notes: pdfIncludeDesignNotes,
            methodology: pdfIncludeMethodology,
          },
          quality_metric_ids: Array.from(selectedReportMetricIds),
          user_insight_ids: Array.from(selectedGeneratedUserInsightIds),
          insights: Array.from(selectedReportInsightIds).map((metricId) => ({
            metric_id: metricId,
            show_observation: true,
            show_evidence: true,
          })),
          include_period_delta: pdfIncludeWeeklyDelta,
          order: {
            insights: Array.from(selectedReportInsightIds),
            user_insights: Array.from(selectedGeneratedUserInsightIds),
          },
        },
      },
    )
  }

  const openStoredPdfPreview = async (reportId: string) => {
    if (!id || !evalId) return
    try {
      const report = await apiClient.callImports.getCallImportEvaluationPdfReport(
        id,
        evalId,
        reportId,
      )
      if (!report.preview_url) {
        throw new Error('Preview URL is not available.')
      }
      if (pdfPreviewUrl?.startsWith('blob:')) {
        window.URL.revokeObjectURL(pdfPreviewUrl)
      }
      setPdfPreviewUrl(report.preview_url)
      setPdfPreviewFilename(report.filename || 'report.pdf')
      setPdfPreviewReportId(reportId)
      setPdfPreviewOpen(true)
      setPdfReportMenuOpen(false)
    } catch (e: unknown) {
      console.error('Failed to open stored PDF report', e)
      showToast(
        getApiErrorMessage(e, 'Failed to open PDF preview.'),
        'error',
      )
    }
  }

  const handlePdfReportSubmit = async () => {
    if (!id || !evalId || pdfReportLoading) return
    const vendorName = pdfVendorName.trim()
    if (!vendorName) {
      setPdfReportError('Vendor name is required.')
      return
    }
    setPdfReportLoadingAction('download')
    setPdfReportError(null)
    try {
      const result = await generatePdfReportBlob(vendorName)
      const vendorSlug =
        vendorName
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, '') || 'client'
      const defaultFilename = `${vendorSlug}-${pdfReportType}-quality-metric-audit-${evalId}.pdf`

      if (result instanceof Blob) {
        downloadBlob(result, defaultFilename)
      } else {
        if (result.id && id && evalId) {
          const blob = await apiClient.callImports.downloadCallImportEvaluationPdfReport(
            id,
            evalId,
            result.id,
          )
          downloadBlob(blob, result.filename || defaultFilename)
        } else {
          const downloadUrl = result.download_url
          if (!downloadUrl) {
            throw new Error('Download URL is not available.')
          }
          const response = await fetch(downloadUrl)
          if (!response.ok) {
            throw new Error('Failed to download PDF report.')
          }
          downloadBlob(
            await response.blob(),
            result.filename || defaultFilename,
          )
        }
        await queryClient.invalidateQueries({
          queryKey: [
            'call-import-evaluation-pdf-reports',
            activeWorkspaceId,
            id,
            evalId,
          ],
        })
      }
      setPdfReportOpen(false)
      setPdfWizardStep(1)
      setPdfVendorName('')
      setPdfReportType('external')
      setPdfIncludeWeeklyDelta(false)
      setPdfUseCase('')
    } catch (e: unknown) {
      console.error('Failed to generate PDF report', e)
      const message = getApiErrorMessage(e, 'Failed to generate PDF report. Please try again.')
      showToast(message, 'error')
    } finally {
      setPdfReportLoadingAction(null)
    }
  }

  const handlePdfPreview = async () => {
    if (!id || !evalId || pdfReportLoading) return
    const vendorName = pdfVendorName.trim()
    if (!vendorName) {
      setPdfReportError('Vendor name is required.')
      return
    }
    setPdfReportLoadingAction('preview')
    setPdfReportError(null)
    try {
      const result = await generatePdfReportBlob(vendorName)
      const vendorSlug =
        vendorName
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, '') || 'client'

      if (result instanceof Blob) {
        if (pdfPreviewUrl?.startsWith('blob:')) {
          window.URL.revokeObjectURL(pdfPreviewUrl)
        }
        const url = window.URL.createObjectURL(result)
        setPdfPreviewUrl(url)
        setPdfPreviewFilename(
          `${vendorSlug}-${pdfReportType}-quality-metric-audit-${evalId}.pdf`,
        )
        setPdfPreviewReportId(null)
      } else {
        if (!result.preview_url) {
          throw new Error('Preview URL is not available.')
        }
        if (pdfPreviewUrl?.startsWith('blob:')) {
          window.URL.revokeObjectURL(pdfPreviewUrl)
        }
        setPdfPreviewUrl(result.preview_url)
        setPdfPreviewFilename(
          result.filename ||
            `${vendorSlug}-${pdfReportType}-quality-metric-audit-${evalId}.pdf`,
        )
        setPdfPreviewReportId(result.id)
        await queryClient.invalidateQueries({
          queryKey: [
            'call-import-evaluation-pdf-reports',
            activeWorkspaceId,
            id,
            evalId,
          ],
        })
      }
      setPdfPreviewOpen(true)
    } catch (e: unknown) {
      console.error('Failed to preview PDF report', e)
      const message = getApiErrorMessage(e, 'Failed to generate PDF preview. Please try again.')
      showToast(message, 'error')
    } finally {
      setPdfReportLoadingAction(null)
    }
  }

  const handlePdfPreviewDownload = async () => {
    if (!pdfPreviewFilename) return
    setPdfPreviewDownloading(true)
    try {
      if (pdfPreviewReportId && id && evalId) {
        const blob = await apiClient.callImports.downloadCallImportEvaluationPdfReport(
          id,
          evalId,
          pdfPreviewReportId,
        )
        downloadBlob(blob, pdfPreviewFilename)
        return
      }
      if (pdfPreviewUrl?.startsWith('blob:')) {
        downloadBlob(
          await fetch(pdfPreviewUrl).then((r) => r.blob()),
          pdfPreviewFilename,
        )
        return
      }
      if (!pdfPreviewUrl) return
      const response = await fetch(pdfPreviewUrl)
      if (!response.ok) {
        throw new Error('Failed to download PDF report.')
      }
      downloadBlob(await response.blob(), pdfPreviewFilename)
    } catch (e: unknown) {
      console.error('Failed to download PDF report', e)
      showToast(
        getApiErrorMessage(e, 'Failed to download PDF report.'),
        'error',
      )
    } finally {
      setPdfPreviewDownloading(false)
    }
  }

  const PDF_WIZARD_STEPS = [
    { id: 1, label: 'Type & comparison' },
    { id: 2, label: 'Details & branding' },
    { id: 3, label: 'Content & metrics' },
    { id: 4, label: 'Preview & generate' },
  ] as const

  const pdfWizardVendorValid = pdfVendorName.trim().length > 0

  const pdfWizardMaxReachableStep = pdfWizardVendorValid ? 4 : 2

  const closePdfReportWizard = () => {
    if (pdfReportLoading) return
    setPdfReportOpen(false)
    setPdfWizardStep(1)
    setPdfReportError(null)
    setPdfGenerationError(null)
  }

  const pdfWizardCanReachStep = (step: number) =>
    step >= 1 && step <= pdfWizardMaxReachableStep

  const handlePdfWizardStepClick = (step: number) => {
    if (!pdfWizardCanReachStep(step) || pdfReportLoading) return
    setPdfReportError(null)
    setPdfWizardStep(step)
  }

  const handlePdfWizardNext = () => {
    if (pdfReportLoading) return
    if (pdfWizardStep === 2 && !pdfWizardVendorValid) {
      setPdfReportError('Vendor name is required.')
      return
    }
    setPdfReportError(null)
    if (pdfWizardStep < 4) setPdfWizardStep((s) => s + 1)
  }

  const handlePdfWizardBack = () => {
    if (pdfReportLoading || pdfWizardStep <= 1) return
    setPdfReportError(null)
    setPdfWizardStep((s) => s - 1)
  }

  const handlePdfWizardGenerateUserInsights = async () => {
    if (!id || !evalId || pdfUserInsightsTriggering) return
    const status = userInsightsQuery.data?.status
    if (status === 'running') return
    setPdfUserInsightsTriggering(true)
    setPdfGenerationError(null)
    try {
      await apiClient.callImports.generateCallImportEvaluationUserInsights(id, evalId, {})
      await userInsightsQuery.refetch()
    } catch (e: any) {
      setPdfGenerationError(
        e?.response?.data?.detail ||
          'Failed to start user insights generation.',
      )
    } finally {
      setPdfUserInsightsTriggering(false)
    }
  }

  const userInsightsNeedsGeneration =
    !userInsightsQuery.data ||
    userInsightsQuery.data.status === 'idle' ||
    userInsightsQuery.data.status === 'failed'

  const metricClustersNeedsGeneration =
    !metricClustersQuery.data ||
    metricClustersQuery.data.status === 'idle' ||
    metricClustersQuery.data.status === 'failed' ||
    metricClustersQuery.data.status === 'cancelled'

  useEffect(() => {
    if (!pdfReportOpen) return
    let cancelled = false
    setReportBrandingLoading(true)
    apiClient
      .getReportBranding()
      .then((branding) => {
        if (!cancelled) {
          setReportBranding(branding)
          setReportHeadingDraft(branding.heading || '')
          syncSelectedBrandImages(branding)
        }
      })
      .catch((e) => {
        console.error('Failed to load report branding', e)
        if (!cancelled) {
          setPdfReportError(
            e?.response?.data?.detail ||
              'Failed to load saved report branding.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setReportBrandingLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pdfReportOpen])

  useEffect(() => {
    if (!pdfReportOpen) setPdfClusterModalOpen(false)
  }, [pdfReportOpen])

  useEffect(() => {
    return () => {
      if (pdfPreviewUrl?.startsWith('blob:')) {
        window.URL.revokeObjectURL(pdfPreviewUrl)
      }
    }
  }, [pdfPreviewUrl])

  useEffect(() => {
    if (!pdfReportMenuOpen) return
    const handleClickOutside = (event: MouseEvent) => {
      if (
        pdfReportMenuRef.current &&
        !pdfReportMenuRef.current.contains(event.target as Node)
      ) {
        setPdfReportMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [pdfReportMenuOpen])

  useEffect(() => {
    if (!pdfReportOpen || !id || !evalId) return
    if (!pdfIncludeWeeklyDelta) {
      setBaselineCandidates([])
      setBaselineEvaluationId(null)
      setBaselineCandidatesError(null)
      return
    }
    let cancelled = false
    setBaselineCandidatesLoading(true)
    setBaselineCandidatesError(null)
    apiClient
      .listCallImportEvaluationBaselineCandidates(id, evalId)
      .then((response) => {
        if (cancelled) return
        setBaselineCandidates(response.items)
        const defaultId =
          response.default_evaluation_id ||
          response.items.find((item) => item.is_default)?.evaluation_id ||
          response.items[0]?.evaluation_id ||
          null
        setBaselineEvaluationId((current) => {
          if (current && response.items.some((item) => item.evaluation_id === current)) {
            return current
          }
          return defaultId
        })
      })
      .catch((e) => {
        console.error('Failed to load baseline candidates', e)
        if (!cancelled) {
          setBaselineCandidates([])
          setBaselineEvaluationId(null)
          setBaselineCandidatesError(
            e?.response?.data?.detail ||
              'Failed to load prior evaluation runs for weekly deltas.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setBaselineCandidatesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pdfReportOpen, pdfIncludeWeeklyDelta, id, evalId])

  const selectedBaselineCandidate = useMemo(
    () =>
      baselineCandidates.find(
        (candidate) => candidate.evaluation_id === baselineEvaluationId,
      ) || null,
    [baselineCandidates, baselineEvaluationId],
  )

  const handleReportLogoUpload = async (
    event: ChangeEvent<HTMLInputElement>,
    role: 'internal' | 'external' | 'generic',
  ) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (!files.length || reportLogoUploading) return
    setReportLogoUploading(true)
    setPdfReportError(null)
    try {
      const branding = await apiClient.uploadReportBrandingImages(files, role)
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
      const newestForRole = [...branding.images]
        .reverse()
        .find((image) => image.role === role)
      if (role === 'internal') {
        setInternalBrandImageId(newestForRole?.id || '')
      } else if (role === 'external') {
        setExternalBrandImageId(newestForRole?.id || '')
      } else {
        syncSelectedBrandImages(branding)
      }
    } catch (e: any) {
      console.error('Failed to upload report logo', e)
      setPdfReportError(
        e?.response?.data?.detail ||
          'Failed to upload images. Use PNG, JPG, WEBP, or SVG up to 5 MB each.',
      )
    } finally {
      setReportLogoUploading(false)
    }
  }

  const handleReportImageDelete = async (imageId: string) => {
    if (reportLogoDeletingId) return
    setReportLogoDeletingId(imageId)
    setPdfReportError(null)
    try {
      const branding = await apiClient.deleteReportBrandingImage(imageId)
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
      syncSelectedBrandImages(branding)
    } catch (e: any) {
      console.error('Failed to remove report image', e)
      setPdfReportError(
        e?.response?.data?.detail || 'Failed to remove saved report image.',
      )
    } finally {
      setReportLogoDeletingId(null)
    }
  }

  const handleReportHeadingSave = async () => {
    setPdfReportError(null)
    try {
      const branding = await apiClient.updateReportBranding({
        heading: reportHeadingDraft.trim() || null,
      })
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
    } catch (e: any) {
      console.error('Failed to save report heading', e)
      setPdfReportError(
        e?.response?.data?.detail || 'Failed to save report heading.',
      )
    }
  }

  return {
    pdfReportMenuOpen,
    setPdfReportMenuOpen,
    pdfReportMenuRef,
    pdfReportsQuery,
    pdfReportOpen,
    setPdfReportOpen,
    pdfWizardStep,
    setPdfWizardStep,
    pdfUserInsightsTriggering,
    pdfClusterModalOpen,
    setPdfClusterModalOpen,
    pdfGenerationError,
    setPdfGenerationError,
    pdfVendorName,
    setPdfVendorName,
    pdfReportType,
    setPdfReportType,
    pdfIncludeWeeklyDelta,
    setPdfIncludeWeeklyDelta,
    baselineCandidates,
    baselineEvaluationId,
    setBaselineEvaluationId,
    baselineCandidatesLoading,
    baselineCandidatesError,
    pdfUseCase,
    setPdfUseCase,
    pdfIncludeAuditSummary,
    setPdfIncludeAuditSummary,
    pdfIncludeQualityPanel,
    setPdfIncludeQualityPanel,
    pdfIncludeUserInsights,
    setPdfIncludeUserInsights,
    pdfIncludeDesignNotes,
    setPdfIncludeDesignNotes,
    pdfIncludeMethodology,
    setPdfIncludeMethodology,
    pdfIncludeFailureDiagnostics,
    setPdfIncludeFailureDiagnostics,
    pdfIncludePromptImprovements,
    setPdfIncludePromptImprovements,
    pdfPreviewOpen,
    setPdfPreviewOpen,
    pdfPreviewUrl,
    setPdfPreviewUrl,
    pdfPreviewFilename,
    pdfPreviewReportId,
    setPdfPreviewReportId,
    pdfPreviewDownloading,
    selectedReportMetricIds,
    setSelectedReportMetricIds,
    selectedReportInsightIds,
    setSelectedReportInsightIds,
    selectedGeneratedUserInsightIds,
    setSelectedGeneratedUserInsightIds,
    pdfReportError,
    setPdfReportError,
    pdfReportLoadingAction,
    pdfReportLoading,
    reportBranding,
    reportHeadingDraft,
    setReportHeadingDraft,
    internalBrandImageId,
    setInternalBrandImageId,
    externalBrandImageId,
    setExternalBrandImageId,
    reportBrandingLoading,
    reportLogoUploading,
    reportLogoDeletingId,
    internalBrandImages,
    externalBrandImages,
    PDF_WIZARD_STEPS,
    pdfWizardVendorValid,
    pdfWizardMaxReachableStep,
    closePdfReportWizard,
    pdfWizardCanReachStep,
    handlePdfWizardStepClick,
    handlePdfWizardNext,
    handlePdfWizardBack,
    handlePdfWizardGenerateUserInsights,
    userInsightsNeedsGeneration,
    metricClustersNeedsGeneration,
    selectedBaselineCandidate,
    handleReportLogoUpload,
    handleReportImageDelete,
    handleReportHeadingSave,
    openStoredPdfPreview,
    handlePdfReportSubmit,
    handlePdfPreview,
    handlePdfPreviewDownload,
  }
}
