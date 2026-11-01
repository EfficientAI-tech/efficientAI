import type { AxiosInstance } from 'axios'
import { uploadFileToPresignedPutUrl } from '../../../lib/presignedUpload'
import type {
  CallImport,
  CallImportDetail,
  CallImportListResponse,
  CallImportRow,
  CallImportSchema,
  CallImportSchemaCreate,
  CallImportSchemaListResponse,
  CallImportSchemaUpdate,
  CallImportStatus,
  CallImportTag,
  CallImportUploadResponse,
  CallImportPreviewResponse,
  CallImportEvaluation,
  CallImportEvaluationBaselineCandidatesResponse,
  CallImportEvaluationExportJob,
  CallImportEvaluationPdfReport,
  CallImportEvaluationPdfReportListResponse,
  CallImportEvaluationLLMOverride,
  CallImportEvaluationListResponse,
  CallImportEvaluationRow,
  CallImportEvaluationRowListResponse,
  CallImportEvaluationRetryResponse,
  CallImportEvaluationBulkActionResponse,
  CallImportEvaluationAggregateResponse,
  CallImportInsightsResponse,
  CallImportTranscribeRequest,
  CallImportTranscribeResponse,
  CallImportRowSelectionFilter,
  CallImportManualAudioPresignResponse,
  CallImportSourceStagePresignResponse,
  CallImportRetryFailedRowsResponse,
  PlatformImportProgress,
  LLMGenerationConfig,
} from '../../../types/api'

export const AUDIO_UPLOAD_CHUNK_SIZE = 25

export interface CallImportAudioUploadProgress {
  chunkIndex: number
  totalChunks: number
  uploadedFiles: number
  totalFiles: number
}

function presignResponseToUploadResponse(
  presign: CallImportManualAudioPresignResponse,
): CallImportUploadResponse {
  return {
    id: presign.call_import_id,
    total_rows: presign.total_rows,
    status: presign.status,
    dataset: presign.dataset,
    tags: presign.tags,
    message: presign.message,
  }
}

export class CallImportsApi {
  constructor(private client: AxiosInstance) {}

  // Call Imports endpoints

  /**
   * Inspect an uploaded CSV / Excel file and get its sheets + headers.
   *
   * Drives the column-mapping UI without forcing the frontend to parse
   * CSV / xlsx itself. CSV files come back as a single synthetic sheet;
   * Excel workbooks come back with one entry per worksheet.
   */
  async previewCallImportFile(file: File): Promise<CallImportPreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await this.client.post(
      '/api/v1/call-imports/preview',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    return response.data
  }

  /** @deprecated Use createCallImport → updateCallImportMapping → startCallImport. */
  async uploadCallImport(
    file: File,
    options: {
      provider: string
      telephonyIntegrationId: string
      /** Reusable Input Parameter schema this upload is mapped against. */
      schemaId: string
      /**
       * Schema-driven mapping: ``{parameter_name: csv_header}``. Must
       * include every required parameter on the schema. Pass an empty
       * string / omit a parameter to leave it unmapped (only allowed
       * for optional parameters).
       */
      parameterMapping: Record<string, string>
      /**
       * CSV/Excel headers the user has explicitly skipped. Every source
       * column must either appear in ``parameterMapping`` or here, or
       * the backend rejects the upload with 400.
       */
      skippedColumns?: string[]
      dataset?: string | null
      tagIds?: string[]
      /**
       * Worksheet name to import when the file is an Excel workbook.
       * Required for .xlsx / .xlsm uploads; must be left undefined / null
       * for CSV uploads (the backend rejects a non-empty value for CSV).
       */
      sheetName?: string | null
    }
  ): Promise<CallImportUploadResponse> {
    const dataset = (options.dataset ?? '').trim() || 'import'
    const staged = await this.createCallImport(file, {
      dataset,
      tagIds: options.tagIds,
      schemaId: options.schemaId,
    })
    await this.updateCallImportMapping(staged.id, {
      schemaId: options.schemaId,
      sheetName: options.sheetName,
      parameterMapping: options.parameterMapping,
      skippedColumns: options.skippedColumns,
    })
    return this.startCallImport(staged.id, {
      provider: options.provider,
      telephonyIntegrationId: options.telephonyIntegrationId,
    })
  }

  /**
   * UPLOAD stage of the staged call-import flow.
   *
   * Persists the CSV / Excel file to S3, captures a sheets snapshot,
   * and creates a ``CallImport`` row with ``status='uploaded'``. The
   * returned record has no mapping / provider / rows yet — the caller
   * follows up with {@link updateCallImportMapping} and
   * {@link startCallImport} to advance the batch.
   */
  async createCallImport(
    file: File,
    options: {
      dataset: string
      tagIds?: string[]
      schemaId?: string | null
      contentModality?: 'chat' | 'voice'
    },
  ): Promise<CallImport> {
    const fileItem = {
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || undefined,
    }
    const presignResponse = await this.client.post<CallImportSourceStagePresignResponse>(
      '/api/v1/call-imports/stage/presign',
      {
        ...fileItem,
        dataset: options.dataset.trim(),
        tag_ids: options.tagIds,
        schema_id: options.schemaId || undefined,
        content_modality: options.contentModality,
      },
    )
    const presign = presignResponse.data
    await uploadFileToPresignedPutUrl(
      presign.upload_url,
      file,
      presign.content_type,
    )
    const completeResponse = await this.client.post<CallImport>(
      '/api/v1/call-imports/stage/complete',
      {
        call_import_id: presign.call_import_id,
        ...fileItem,
        dataset: options.dataset.trim(),
        tag_ids: options.tagIds,
        schema_id: options.schemaId || undefined,
        content_modality: options.contentModality,
      },
    )
    return completeResponse.data
  }

  private async presignManualAudioUpload(
    files: File[],
    options: {
      dataset?: string
      tagIds?: string[]
      batchName?: string
      importId?: string
    },
  ): Promise<CallImportManualAudioPresignResponse> {
    const fileItems = files.map((file) => ({
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || undefined,
    }))
    if (options.importId) {
      const response = await this.client.post<CallImportManualAudioPresignResponse>(
        `/api/v1/call-imports/${options.importId}/audio-append/presign`,
        { files: fileItems },
      )
      return response.data
    }
    const response = await this.client.post<CallImportManualAudioPresignResponse>(
      '/api/v1/call-imports/audio-upload/presign',
      {
        files: fileItems,
        dataset: options.dataset?.trim(),
        batch_name: options.batchName?.trim() || undefined,
        tag_ids: options.tagIds,
      },
    )
    return response.data
  }

  private async completeManualAudioUpload(
    importId: string,
    rowIds: string[],
  ): Promise<void> {
    await this.client.post(
      `/api/v1/call-imports/${importId}/manual-audio/complete`,
      { row_ids: rowIds },
    )
  }

  private async uploadManualAudioFilesViaPresign(
    files: File[],
    options: {
      dataset?: string
      tagIds?: string[]
      batchName?: string
      importId?: string
    },
  ): Promise<CallImportUploadResponse> {
    const presign = await this.presignManualAudioUpload(files, options)
    const pending = [...files]
    const rowIds: string[] = []
    for (const slot of presign.uploads) {
      const matchIndex = pending.findIndex((file) => file.name === slot.filename)
      const file = matchIndex >= 0 ? pending.splice(matchIndex, 1)[0] : null
      if (!file) {
        throw new Error(`Missing local file for ${slot.filename}`)
      }
      await uploadFileToPresignedPutUrl(
        slot.upload_url,
        file,
        slot.content_type,
      )
      rowIds.push(slot.row_id)
    }
    await this.completeManualAudioUpload(presign.call_import_id, rowIds)
    return presignResponseToUploadResponse(presign)
  }

  /** @deprecated Prefer presigned upload via uploadCallImportAudioChunked. */
  async uploadCallImportAudio(
    files: File[],
    options: {
      dataset: string
      tagIds?: string[]
      batchName?: string
    },
  ): Promise<CallImportUploadResponse> {
    return this.uploadManualAudioFilesViaPresign(files, options)
  }

  async appendCallImportAudio(
    importId: string,
    files: File[],
  ): Promise<CallImportUploadResponse> {
    return this.uploadManualAudioFilesViaPresign(files, { importId })
  }

  async uploadCallImportAudioChunked(
    files: File[],
    options: {
      dataset: string
      tagIds?: string[]
      batchName?: string
      onProgress?: (progress: CallImportAudioUploadProgress) => void
    },
  ): Promise<CallImportUploadResponse> {
    if (files.length === 0) {
      throw new Error('At least one audio file is required.')
    }

    const chunks: File[][] = []
    for (let i = 0; i < files.length; i += AUDIO_UPLOAD_CHUNK_SIZE) {
      chunks.push(files.slice(i, i + AUDIO_UPLOAD_CHUNK_SIZE))
    }

    let result: CallImportUploadResponse | null = null
    for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex += 1) {
      const chunk = chunks[chunkIndex]
      options.onProgress?.({
        chunkIndex: chunkIndex + 1,
        totalChunks: chunks.length,
        uploadedFiles: chunkIndex * AUDIO_UPLOAD_CHUNK_SIZE,
        totalFiles: files.length,
      })

      if (chunkIndex === 0) {
        result = await this.uploadManualAudioFilesViaPresign(chunk, {
          dataset: options.dataset,
          tagIds: options.tagIds,
          batchName: options.batchName,
        })
      } else {
        result = await this.uploadManualAudioFilesViaPresign(chunk, {
          importId: result!.id,
        })
      }

      options.onProgress?.({
        chunkIndex: chunkIndex + 1,
        totalChunks: chunks.length,
        uploadedFiles: Math.min(
          (chunkIndex + 1) * AUDIO_UPLOAD_CHUNK_SIZE,
          files.length,
        ),
        totalFiles: files.length,
      })
    }

    return result!
  }

  async uploadCallImportAudioAppendChunked(
    importId: string,
    files: File[],
    options?: {
      onProgress?: (progress: CallImportAudioUploadProgress) => void
    },
  ): Promise<CallImportUploadResponse> {
    if (files.length === 0) {
      throw new Error('At least one audio file is required.')
    }

    const chunks: File[][] = []
    for (let i = 0; i < files.length; i += AUDIO_UPLOAD_CHUNK_SIZE) {
      chunks.push(files.slice(i, i + AUDIO_UPLOAD_CHUNK_SIZE))
    }

    let result: CallImportUploadResponse | null = null
    for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex += 1) {
      const chunk = chunks[chunkIndex]
      options?.onProgress?.({
        chunkIndex: chunkIndex + 1,
        totalChunks: chunks.length,
        uploadedFiles: chunkIndex * AUDIO_UPLOAD_CHUNK_SIZE,
        totalFiles: files.length,
      })

      result = await this.uploadManualAudioFilesViaPresign(chunk, {
        importId,
      })

      options?.onProgress?.({
        chunkIndex: chunkIndex + 1,
        totalChunks: chunks.length,
        uploadedFiles: Math.min(
          (chunkIndex + 1) * AUDIO_UPLOAD_CHUNK_SIZE,
          files.length,
        ),
        totalFiles: files.length,
      })
    }

    return result!
  }

  /**
   * MAP stage of the staged call-import flow.
   *
   * Persists the schema + sheet + parameter mapping on the batch. The
   * backend validates against the sheet snapshot it cached at upload
   * time, so this is purely a metadata operation (no S3 fetch).
   * Idempotent: safe to call repeatedly while the batch is in
   * ``uploaded`` or ``mapped`` state.
   */
  async updateCallImportMapping(
    id: string,
    options: {
      schemaId: string
      sheetName?: string | null
      parameterMapping: Record<string, string>
      skippedColumns?: string[]
    },
  ): Promise<CallImport> {
    const response = await this.client.patch(
      `/api/v1/call-imports/${id}/mapping`,
      {
        schema_id: options.schemaId,
        sheet_name: options.sheetName ?? null,
        parameter_mapping: options.parameterMapping,
        skipped_columns: options.skippedColumns ?? [],
      },
    )
    return response.data
  }

  /**
   * IMPORT stage of the staged call-import flow.
   *
   * Materialises rows from the staged source file using the persisted
   * mapping and fans them out to the ``imports`` Celery queue. Returns
   * the same shape as the legacy one-shot ``uploadCallImport``.
   */
  async startCallImport(
    id: string,
    options: {
      provider: string | null
      telephonyIntegrationId: string | null
    },
  ): Promise<CallImportUploadResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${id}/import`,
      {
        provider: options.provider,
        telephony_integration_id: options.telephonyIntegrationId,
      },
    )
    return response.data
  }

  // -------------------------------------------------------------------
  // Call Import Schemas (reusable Input Parameter schemas)
  // -------------------------------------------------------------------

  async listCallImportSchemas(): Promise<CallImportSchemaListResponse> {
    const response = await this.client.get('/api/v1/call-import-schemas')
    return response.data
  }

  async getCallImportSchema(id: string): Promise<CallImportSchema> {
    const response = await this.client.get(`/api/v1/call-import-schemas/${id}`)
    return response.data
  }

  async createCallImportSchema(
    payload: CallImportSchemaCreate,
  ): Promise<CallImportSchema> {
    const response = await this.client.post('/api/v1/call-import-schemas', payload)
    return response.data
  }

  async updateCallImportSchema(
    id: string,
    payload: CallImportSchemaUpdate,
  ): Promise<CallImportSchema> {
    const response = await this.client.patch(
      `/api/v1/call-import-schemas/${id}`,
      payload,
    )
    return response.data
  }

  async deleteCallImportSchema(
    id: string,
    options?: { force?: boolean },
  ): Promise<void> {
    await this.client.delete(`/api/v1/call-import-schemas/${id}`, {
      params: options?.force ? { force: true } : undefined,
    })
  }

  async previewPlatformCallImport(payload: {
    voice_integration_id: string
    window_start: string
    window_end: string
    window_timezone?: string
    dataset?: string
    filters?: {
      agent_ids?: string[]
      min_duration_seconds?: number
      speed?: string
      import_provider_transcript?: boolean
      medium?: 'voice' | 'chat'
      agents?: Array<{ id: string; name: string; medium?: string | null }>
    }
  }): Promise<{
    recordings_in_window: number
    recordings_count_complete: boolean
    count_pages_scanned?: number
    discovery_slices?: number
    sample_count: number
    samples: Array<{
      conversation_id: string
      agent_id?: string | null
      started_at?: string | null
      status?: string | null
    }>
  }> {
    const response = await this.client.post('/api/v1/call-imports/platform/preview', payload)
    return response.data
  }

  async createPlatformCallImport(payload: {
    voice_integration_id: string
    window_start: string
    window_end: string
    window_timezone?: string
    name?: string
    dataset?: string
    max_calls?: number
    filters?: {
      agent_ids?: string[]
      min_duration_seconds?: number
      speed?: string
      import_provider_transcript?: boolean
      medium?: 'voice' | 'chat'
      agents?: Array<{ id: string; name: string; medium?: string | null }>
    }
  }, idempotencyKey?: string): Promise<{ id: string; status: string; discovery_status?: string }> {
    const response = await this.client.post('/api/v1/call-imports/platform', payload, {
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    })
    return response.data
  }

  async pausePlatformImport(importId: string): Promise<{ status: string }> {
    const response = await this.client.post(`/api/v1/call-imports/platform/${importId}/pause`)
    return response.data
  }

  async resumePlatformImport(importId: string): Promise<{ status: string }> {
    const response = await this.client.post(`/api/v1/call-imports/platform/${importId}/resume`)
    return response.data
  }

  async retryPlatformDiscovery(importId: string): Promise<{ status: string }> {
    const response = await this.client.post(
      `/api/v1/call-imports/platform/${importId}/retry-discovery`,
    )
    return response.data
  }

  async listPlatformImportAgents(
    integrationId: string,
  ): Promise<Array<{ id: string; name: string; medium?: string | null }>> {
    const response = await this.client.get('/api/v1/call-imports/platform/agents', {
      params: { integration_id: integrationId },
    })
    return response.data
  }

  async getPlatformImportProgress(importId: string): Promise<PlatformImportProgress> {
    const response = await this.client.get(
      `/api/v1/call-imports/platform/${importId}/progress`,
    )
    return response.data
  }

  async listCallImports(
    params: {
      page?: number
      page_size?: number
      status?: CallImportStatus
      dataset?: string
      tag_id?: string[]
      source_format?: string
    } = {}
  ): Promise<CallImportListResponse> {
    // Send tag_id repeated rather than as a JSON array.
    const search = new URLSearchParams()
    if (params.page !== undefined) search.set('page', String(params.page))
    if (params.page_size !== undefined) search.set('page_size', String(params.page_size))
    if (params.status) search.set('status', params.status)
    if (params.dataset !== undefined) search.set('dataset', params.dataset)
    if (params.source_format) search.set('source_format', params.source_format)
    for (const tag of params.tag_id || []) search.append('tag_id', tag)
    const response = await this.client.get('/api/v1/call-imports', { params: search })
    return response.data
  }

  async listCallImportDatasets(): Promise<string[]> {
    const response = await this.client.get('/api/v1/call-imports/datasets')
    return response.data
  }

  async getCallImport(
    id: string,
    params: {
      row_limit?: number
      row_offset?: number
      q?: string
      /**
       * Optional filter on ``CallImportRow.diarised_transcript_status``.
       * When set, ``filtered_total_rows`` on the response reflects the
       * post-filter row count (combined with ``q`` when both are
       * supplied) so the UI can paginate against the same slice.
       */
      diarised_status?: 'pending' | 'running' | 'completed' | 'failed'
    } = {}
  ): Promise<CallImportDetail> {
    const response = await this.client.get(`/api/v1/call-imports/${id}`, { params })
    return response.data
  }

  async getCallImportRow(id: string, rowId: string): Promise<CallImportRow> {
    const response = await this.client.get(
      `/api/v1/call-imports/${id}/rows/${rowId}`,
    )
    return response.data
  }

  async listCallImportRowIds(
    id: string,
    params: {
      q?: string
      diarised_status?: 'pending' | 'running' | 'completed' | 'failed'
    } = {}
  ): Promise<{ ids: string[]; total: number }> {
    const response = await this.client.get(
      `/api/v1/call-imports/${id}/row-ids`,
      { params },
    )
    return response.data
  }

  async updateCallImport(
    id: string,
    payload: {
      original_filename?: string | null
      dataset?: string | null
      tag_ids?: string[]
      /**
       * Reassign the Input Parameter schema. Only honoured while the
       * batch is in ``uploaded`` / ``mapped`` state. Switching schemas
       * resets the mapping and rewinds the batch to ``uploaded``.
       */
      schema_id?: string | null
    },
  ): Promise<CallImport> {
    const response = await this.client.patch(`/api/v1/call-imports/${id}`, payload)
    return response.data
  }

  async deleteCallImport(
    id: string,
  ): Promise<{ id: string; status: 'accepted' | 'completed' }> {
    const response = await this.client.delete(`/api/v1/call-imports/${id}`)
    return response.data
  }

  async deleteCallImportRow(id: string, rowId: string): Promise<void> {
    await this.client.delete(`/api/v1/call-imports/${id}/rows/${rowId}`)
  }

  async bulkDeleteCallImportRows(
    id: string,
    options:
      | { rowIds: string[] }
      | { rowFilter: CallImportRowSelectionFilter },
  ): Promise<{ deleted: number; status?: 'completed' | 'accepted' }> {
    const body =
      'rowFilter' in options
        ? { row_filter: options.rowFilter }
        : { row_ids: options.rowIds }
    const response = await this.client.post(
      `/api/v1/call-imports/${id}/rows/bulk-delete`,
      body,
    )
    return response.data
  }

  async createCallImportEvaluation(
    callImportId: string,
    payload: {
      metric_ids: string[]
      name?: string | null
      /**
       * Which transcript to score against. ``'diarised'`` (default)
       * auto-diarizes then scores; ``'production'`` scores the CSV
       * transcript directly.
       */
      transcript_sources?: Array<'production' | 'diarised'>
      /** Run-level LLM provider key. Leave undefined for legacy default. */
      llm_provider?: string | null
      llm_model?: string | null
      llm_credential_id?: string | null
      llm_config?: LLMGenerationConfig | null
      /** Per-metric LLM override map keyed by metric UUID. */
      metric_llm_overrides?: Record<string, CallImportEvaluationLLMOverride> | null
      /** When true, diarize rows missing transcripts before evaluation. */
      auto_transcribe?: boolean
      transcribe_overwrite?: boolean
      /**
       * Diarisation pipeline shape for the auto-transcribe step.
       * 'stt_llm' (default) runs STT then an LLM diariser over the
       * resulting text. 'llm_only' skips STT and feeds the audio
       * directly to the multimodal ``diarization_llm_*`` model — STT
       * fields must be omitted in that case.
       */
      transcribe_mode?: 'stt_llm' | 'llm_only'
      stt_provider?: string | null
      stt_model?: string | null
      stt_credential_id?: string | null
      stt_language?: string | null
      /**
       * LLM diariser config: post-STT, an LLM splits the plain
       * transcript into agent/user turns using ``diarization_prompt``
       * (or the canonical default when empty). Required by the server
       * when ``auto_transcribe`` is set. Also used in 'llm_only' mode
       * where this same LLM receives the audio directly.
       */
      diarization_llm_provider?: string | null
      diarization_llm_model?: string | null
      diarization_llm_credential_id?: string | null
      diarization_prompt?: string | null
      /**
       * Opt into LLM-driven discovery of brand-new top-level metrics
       * for this run. Surfaces candidates in the Discovered metrics
       * panel on the evaluation detail Flow tab.
       */
      discover_new_metrics?: boolean
      /** Telephony credentials when starting from a mapped batch. */
      provider?: string | null
      telephony_integration_id?: string | null
    },
  ): Promise<CallImportEvaluation> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations`,
      payload,
    )
    return response.data
  }

  /** Aggregated metric distributions for a single evaluation run. */
  async getCallImportEvaluationAggregate(
    callImportId: string,
    evaluationId: string,
    baselineEvaluationId?: string | null,
  ): Promise<CallImportEvaluationAggregateResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/aggregate`,
      {
        params: baselineEvaluationId
          ? { baseline_evaluation_id: baselineEvaluationId }
          : undefined,
      },
    )
    return response.data
  }

  /**
   * Read the cached LLM TLDR for an evaluation. Returns ``null`` when
   * the user has never generated one (the empty-state CTA renders
   * this case).
   */
  async getCallImportEvaluationInsights(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').EvaluationTldrSummary | null> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/insights`,
    )
    return response.data ?? null
  }

  /**
   * Generate (or return cached) the LLM TLDR for an evaluation run.
   *
   * - Pass ``regenerate: true`` to force a fresh LLM call even when a
   *   cached summary exists at the current ``completed_rows`` watermark.
   * - Pass ``provider`` + ``model`` to pin a specific LLM. Omit both to
   *   let the backend auto-detect the org's first active OpenAI /
   *   Anthropic / Google credential (mirroring Prompt Partials).
   */
  async generateCallImportEvaluationInsights(
    callImportId: string,
    evaluationId: string,
    options?: {
      regenerate?: boolean
      provider?: string | null
      model?: string | null
      credential_id?: string | null
      max_llm_calls?: number | null
    },
  ): Promise<import('../../../types/api').EvaluationTldrSummary> {
    const body: Record<string, unknown> = {
      regenerate: Boolean(options?.regenerate),
    }
    if (options?.provider) body.provider = options.provider
    if (options?.model) body.model = options.model
    if (options?.credential_id) body.credential_id = options.credential_id
    if (options?.max_llm_calls != null) body.max_llm_calls = options.max_llm_calls
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/insights`,
      body,
    )
    return response.data
  }

  async getCallImportEvaluationUserInsights(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').EvaluationUserInsightsState | null> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/user-insights`,
    )
    return response.data
  }

  async getCallImportEvaluationMetricClusters(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').EvaluationMetricClustersState | null> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/metric-clusters`,
    )
    return response.data
  }

  async getCallImportEvaluationPromptImprovements(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').EvaluationPromptImprovementsState | null> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/prompt-improvements`,
    )
    return response.data
  }

  async generateCallImportEvaluationPromptImprovements(
    callImportId: string,
    evaluationId: string,
    data: {
      imported_agent_id?: string
      regenerate?: boolean
      force?: boolean
      provider?: string
      model?: string
      credential_id?: string
    },
  ): Promise<import('../../../types/api').EvaluationPromptImprovementsState> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/prompt-improvements`,
      data,
    )
    return response.data
  }

  async reviewCallImportEvaluationPromptImprovement(
    callImportId: string,
    evaluationId: string,
    data: {
      suggestion_id: string
      review_status: 'pending' | 'accepted' | 'rejected'
      edited_text?: string | null
    },
  ): Promise<import('../../../types/api').EvaluationPromptImprovementsState> {
    const response = await this.client.patch(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/prompt-improvements/review`,
      data,
    )
    return response.data
  }

  async previewCallImportEvaluationPromptPush(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').PromptPushPreview> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/prompt-improvements/push-preview`,
    )
    return response.data
  }

  async pushCallImportEvaluationPrompt(
    callImportId: string,
    evaluationId: string,
    confirm: string,
    options?: { pushToLive?: boolean },
  ): Promise<import('../../../types/api').PromptPushRecord> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/prompt-improvements/push`,
      { confirm, push_to_live: options?.pushToLive ?? true },
    )
    return response.data
  }

  async listCallImportEvaluationMetricClusterEligibleRows(
    callImportId: string,
    evaluationId: string,
    options?: {
      limit?: number
      count_only?: boolean
    },
  ): Promise<import('../../../types/api').MetricClusterEligibleRowsResponse> {
    const params = new URLSearchParams()
    if (options?.limit != null) params.set('limit', String(options.limit))
    if (options?.count_only) params.set('count_only', 'true')
    const query = params.toString()
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/metric-clusters/eligible-rows${query ? `?${query}` : ''}`,
    )
    return response.data
  }

  async getCallImportEvaluationMetricClusterFailurePolicies(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').MetricFailurePoliciesResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/metric-clusters/failure-policies`,
    )
    return response.data
  }

  async saveCallImportEvaluationMetricClusterFailurePolicies(
    callImportId: string,
    evaluationId: string,
    policies: Record<string, import('../../../types/api').MetricFailurePolicy>,
  ): Promise<import('../../../types/api').MetricFailurePoliciesResponse> {
    const response = await this.client.put(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/metric-clusters/failure-policies`,
      { policies, source: 'user' },
    )
    return response.data
  }

  async generateCallImportEvaluationMetricClusters(
    callImportId: string,
    evaluationId: string,
    options?: {
      regenerate?: boolean
      force?: boolean
      provider?: string | null
      model?: string | null
      credential_id?: string | null
      max_llm_calls?: number | null
      evaluation_row_ids?: string[] | null
      row_limit?: number | null
      failure_policies?: Record<
        string,
        import('../../../types/api').MetricFailurePolicy
      > | null
    },
  ): Promise<import('../../../types/api').EvaluationMetricClustersState> {
    const body: Record<string, unknown> = {
      regenerate: Boolean(options?.regenerate),
      force: Boolean(options?.force),
    }
    if (options?.provider) body.provider = options.provider
    if (options?.model) body.model = options.model
    if (options?.credential_id) body.credential_id = options.credential_id
    if (options?.max_llm_calls != null) body.max_llm_calls = options.max_llm_calls
    if (options?.evaluation_row_ids?.length) {
      body.evaluation_row_ids = options.evaluation_row_ids
    }
    if (options?.row_limit != null) body.row_limit = options.row_limit
    if (options?.failure_policies) {
      body.failure_policies = options.failure_policies
    }
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/metric-clusters`,
      body,
    )
    return response.data
  }

  async cancelCallImportEvaluationMetricClusters(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').EvaluationMetricClustersState> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/metric-clusters/cancel`,
    )
    return response.data
  }

  async generateCallImportEvaluationUserInsights(
    callImportId: string,
    evaluationId: string,
    options?: {
      regenerate?: boolean
      force?: boolean
      provider?: string | null
      model?: string | null
      credential_id?: string | null
      max_llm_calls?: number | null
    },
  ): Promise<import('../../../types/api').EvaluationUserInsightsState> {
    const body: Record<string, unknown> = {
      regenerate: Boolean(options?.regenerate),
      force: Boolean(options?.force),
    }
    if (options?.provider) body.provider = options.provider
    if (options?.model) body.model = options.model
    if (options?.credential_id) body.credential_id = options.credential_id
    if (options?.max_llm_calls != null) body.max_llm_calls = options.max_llm_calls
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/user-insights`,
      body,
    )
    return response.data
  }

  /**
   * Aggregate flow chart for a parent metric: returns nodes/edges built
   * from per-row LLM-inferred ``sequence`` arrays. Used by the React
   * Flow visualisation on the evaluation overview.
   */
  async getCallImportEvaluationFlow(
    callImportId: string,
    evaluationId: string,
    parentMetricId: string,
  ): Promise<import('../../../types/api').MetricFlowResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/flow`,
      { params: { parent_metric_id: parentMetricId } },
    )
    return response.data
  }

  /**
   * List LLM-discovered candidate sub-labels for a parent metric in an
   * evaluation. Returned items power the Discovered Labels panel where
   * users decide which candidates to promote or merge.
   */
  async getCallImportEvaluationDiscoveredLabels(
    callImportId: string,
    evaluationId: string,
    parentMetricId: string,
  ): Promise<import('../../../types/api').DiscoveredLabelsResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/discovered-labels`,
      { params: { parent_metric_id: parentMetricId } },
    )
    return response.data
  }

  /**
   * Merge a discovered slug into another within an evaluation. Rewrites
   * every row's discovered_labels and sequence array so the panel +
   * flow chart converge on the surviving slug.
   */
  async mergeCallImportEvaluationDiscoveredLabels(
    callImportId: string,
    evaluationId: string,
    body: { parent_metric_id: string; from_key: string; to_key: string },
  ): Promise<import('../../../types/api').DiscoveredLabelsResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/discovered-labels/merge`,
      body,
    )
    return response.data
  }

  /**
   * Delete (tombstone) an LLM-discovered candidate. Strips the slug
   * from every row's discovered_labels + sequence and records a
   * deletion alias on the evaluation so workers finishing later don't
   * resurrect it. Use for gibberish candidates the LLM proposed.
   */
  async deleteCallImportEvaluationDiscoveredLabel(
    callImportId: string,
    evaluationId: string,
    body: { parent_metric_id: string; key: string },
  ): Promise<import('../../../types/api').DiscoveredLabelsResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/discovered-labels/delete`,
      body,
    )
    return response.data
  }

  /**
   * Promote an LLM-discovered candidate into a real child Metric under
   * the given parent. ``key`` must equal ``slugify(name)`` so existing
   * rows' sequence arrays auto-resolve against the new child.
   *
   * ``capture_rationale`` defaults to true on the backend (matches the
   * Discovered Labels UX: candidates are LLM-suggested with rationales,
   * so the user almost always wants future rows that hit them to keep
   * capturing rationales).
   */
  async promoteDiscoveredChild(
    parentMetricId: string,
    body: {
      key: string
      name: string
      description?: string | null
      capture_rationale?: boolean
    },
  ): Promise<import('../../../types/api').MetricSummary> {
    const response = await this.client.post(
      `/api/v1/metrics/${parentMetricId}/children/from-discovered`,
      body,
    )
    return response.data
  }

  /**
   * List LLM-discovered candidate TOP-LEVEL metrics for an evaluation.
   * Mirrors :func:`getCallImportEvaluationDiscoveredLabels` but is
   * scoped to the evaluation as a whole (no ``parent_metric_id``).
   * Returns an empty ``items`` list when the evaluation didn't opt
   * into top-level metric discovery, so callers can fetch
   * unconditionally.
   */
  async getCallImportEvaluationDiscoveredMetrics(
    callImportId: string,
    evaluationId: string,
  ): Promise<import('../../../types/api').DiscoveredMetricsResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/discovered-metrics`,
    )
    return response.data
  }

  /**
   * Merge one discovered top-level metric slug into another. Rewrites
   * every row's ``__discovered_metrics__`` list and records the
   * alias on the evaluation so workers finishing later converge on
   * the surviving slug.
   */
  async mergeCallImportEvaluationDiscoveredMetrics(
    callImportId: string,
    evaluationId: string,
    body: { from_key: string; to_key: string },
  ): Promise<import('../../../types/api').DiscoveredMetricsResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/discovered-metrics/merge`,
      body,
    )
    return response.data
  }

  /**
   * Tombstone an LLM-discovered top-level metric candidate. Strips
   * the slug from every row's ``__discovered_metrics__`` list and
   * records a deletion alias on the evaluation so workers finishing
   * later can't resurrect it.
   */
  async deleteCallImportEvaluationDiscoveredMetric(
    callImportId: string,
    evaluationId: string,
    body: { key: string },
  ): Promise<import('../../../types/api').DiscoveredMetricsResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/discovered-metrics/delete`,
      body,
    )
    return response.data
  }

  /**
   * Promote an LLM-discovered top-level metric candidate into a real
   * standalone :class:`Metric` row. ``key`` must equal
   * ``slugify(name)`` so already-scored rows that referenced the
   * candidate keep resolving against the promoted metric.
   *
   * ``metric_type`` selects how the new metric will be scored on
   * future runs (``boolean`` / ``rating`` / ``category``). ``category``
   * creates a ``multi_label`` parent with no children — the user adds
   * children via the existing Metrics page.
   */
  async promoteDiscoveredMetric(body: {
    key: string
    name: string
    description?: string | null
    metric_type?: 'boolean' | 'rating' | 'category'
    capture_rationale?: boolean
    custom_config?: Record<string, unknown> | null
  }): Promise<import('../../../types/api').MetricSummary> {
    const response = await this.client.post(
      `/api/v1/metrics/from-discovered`,
      body,
    )
    return response.data
  }

  /** Cross-run insights for the call import detail page. */
  async getCallImportInsights(
    callImportId: string,
  ): Promise<CallImportInsightsResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/insights`,
    )
    return response.data
  }

  /**
   * Fetch the canonical LLM diariser prompt. Used by the Transcribe /
   * Run Evaluation modals to pre-fill the prompt textarea so the
   * operator sees the actual default they'd otherwise get.
   */
  async getCallImportDiarisationPromptDefault(): Promise<string> {
    const response = await this.client.get(
      `/api/v1/call-imports/diarisation-prompt-default`,
    )
    return (response.data?.prompt ?? '') as string
  }

  /** Fan out diarization tasks for a batch of rows. */
  async transcribeCallImport(
    callImportId: string,
    payload: CallImportTranscribeRequest,
  ): Promise<CallImportTranscribeResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/transcribe`,
      payload,
    )
    return response.data
  }

  /** Diarize a single row's recording. */
  async transcribeCallImportRow(
    callImportId: string,
    rowId: string,
    payload: CallImportTranscribeRequest,
  ): Promise<CallImportTranscribeResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/rows/${rowId}/transcribe`,
      payload,
    )
    return response.data
  }

  /**
   * Re-enqueue every failed import row in this batch.
   *
   * Rows are reset to `pending` first so the UI can immediately show that
   * the retry sweep started; rows that fail to enqueue again are returned
   * in `enqueue_failed` and stay `failed`.
   */
  async retryFailedCallImportRows(
    callImportId: string,
    options?: {
      provider: string | null
      telephonyIntegrationId: string | null
    },
  ): Promise<CallImportRetryFailedRowsResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/retry-failed`,
      options
        ? {
            provider: options.provider,
            telephony_integration_id: options.telephonyIntegrationId,
          }
        : undefined,
    )
    return response.data
  }

  /**
   * Abort an in-flight (or queued) diarisation for a single row.
   *
   * Idempotent — calling on a row whose diarisation is already in a
   * terminal state (``completed`` / ``failed`` / ``idle``) returns the
   * row unchanged so the UI can wire this to a "Stop" button without
   * pre-checking state. The backend flips the row's
   * ``diarised_transcript_status`` to ``failed`` and stamps
   * ``"Diarisation cancelled by user"`` as the error so the existing
   * diarisation pill in the row header renders the right state on the
   * next poll.
   */
  async cancelCallImportRowDiarisation(
    callImportId: string,
    rowId: string,
  ): Promise<CallImportRow> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/rows/${rowId}/cancel-diarisation`,
    )
    return response.data
  }

  /**
   * Abort in-flight diarisation for many rows in one call.
   *
   * Pass ``rowIds`` to cancel a specific subset. Omit it (or pass
   * ``null``) to cancel every row in the import whose
   * ``diarised_transcript_status`` is currently ``pending`` or
   * ``running`` — the "stop everything" affordance.
   */
  async cancelCallImportDiarisation(
    callImportId: string,
    options?: { rowIds?: string[] | null; rowFilter?: CallImportRowSelectionFilter | null },
  ): Promise<{ cancelled: number; skipped: number }> {
    let body: Record<string, unknown> = {}
    if (options?.rowFilter) {
      body = { row_filter: options.rowFilter }
    } else if (options?.rowIds !== undefined && options.rowIds !== null) {
      body = { row_ids: options.rowIds }
    }
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/cancel-diarisation`,
      body,
    )
    return response.data
  }

  /**
   * Flip ``diarised_speaker_swap`` on a row and re-render
   * ``diarised_transcript`` from ``diarised_segments``. Returns the
   * updated row so the caller can swap it into local state without an
   * extra refetch.
   *
   * The backend rejects this with 409 when the row has no structured
   * segments (e.g. legacy diarisations done before turns were
   * persisted) — callers should surface that as "re-diarise to enable
   * speaker swapping".
   */
  async toggleCallImportRowSpeakerSwap(
    callImportId: string,
    rowId: string,
  ): Promise<CallImportRow> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/rows/${rowId}/diarised-speaker-swap`,
    )
    return response.data
  }

  async updateCallImportEvaluation(
    callImportId: string,
    evaluationId: string,
    payload: { name?: string | null },
  ): Promise<CallImportEvaluation> {
    const response = await this.client.patch(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}`,
      payload,
    )
    return response.data
  }

  async bulkDeleteCallImportEvaluations(
    callImportId: string,
    evaluationIds: string[],
  ): Promise<{ deleted: number }> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/bulk-delete`,
      { evaluation_ids: evaluationIds },
    )
    return response.data
  }

  async deleteCallImportEvaluationRow(
    callImportId: string,
    evaluationId: string,
    evalRowId: string,
  ): Promise<void> {
    await this.client.delete(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/rows/${evalRowId}`,
    )
  }

  /**
   * Re-enqueue failed evaluation rows. With no body, every row in the
   * run whose status is ``failed`` is re-run with the run's saved
   * config. Pass ``evalRowIds`` to scope the retry to a subset (used
   * by the per-row "Retry" button), and/or the ``llm_*`` / ``stt_*``
   * fields to swap out the LLM / STT provider before re-enqueueing
   * (the backend validates + persists them onto the run).
   *
   * Rows still in progress / already completed are silently skipped
   * on the server and reported in the response's ``skipped`` list —
   * the mutation never fails just because the caller's selection is
   * stale.
   */
  async retryCallImportEvaluation(
    callImportId: string,
    evaluationId: string,
    options?: {
      evalRowIds?: string[]
      rowFilter?: import('../../../types/api').CallImportEvaluationRowRetryFilter | null
      llmProvider?: string | null
      llmModel?: string | null
      llmCredentialId?: string | null
      llmConfig?: LLMGenerationConfig | null
      sttProvider?: string | null
      sttModel?: string | null
      sttCredentialId?: string | null
      transcribeOverwrite?: boolean
      transcribeMode?: 'stt_llm' | 'llm_only'
      diarizationLlmProvider?: string | null
      diarizationLlmModel?: string | null
      diarizationLlmCredentialId?: string | null
      diarizationPrompt?: string | null
      /**
       * Override telephony credentials on the batch when failed rows must
       * re-fetch recordings. Send both fields together; omit to keep the
       * batch's existing pinned credentials.
       */
      provider?: string | null
      telephonyIntegrationId?: string | null
      /**
       * Metric-subset retry: when set, only these metrics are
       * recomputed and merged into the row's existing metric_scores
       * (other metrics' previous values are preserved). The backend
       * auto-flips ``include_completed`` to true in this case so
       * already-successful rows are eligible.
       */
      metricIds?: string[]
      /**
       * When true, rows currently ``completed`` are eligible for
       * retry too (otherwise only ``failed`` rows are picked up).
       * Required-and-implied when ``metricIds`` is set.
       */
      includeCompleted?: boolean
      /**
       * Per-metric LLM overrides, keyed by leaf metric id. Replaces the
       * run's stored overrides, so callers should merge with the existing
       * map. Used to route classification metrics to a System 1 model.
       */
      metricLlmOverrides?: Record<string, CallImportEvaluationLLMOverride>
    },
  ): Promise<CallImportEvaluationRetryResponse> {
    const body: Record<string, unknown> = {}
    if (options?.evalRowIds && options.evalRowIds.length > 0) {
      body.eval_row_ids = options.evalRowIds
    }
    if (options?.rowFilter) {
      body.row_filter = options.rowFilter
    }
    if (options?.llmProvider) body.llm_provider = options.llmProvider
    if (options?.llmModel) body.llm_model = options.llmModel
    if (options?.llmCredentialId !== undefined) {
      body.llm_credential_id = options.llmCredentialId
    }
    if (options?.llmConfig !== undefined) {
      body.llm_config = options.llmConfig
    }
    if (options?.metricLlmOverrides !== undefined) {
      body.metric_llm_overrides = options.metricLlmOverrides
    }
    if (options?.sttProvider) body.stt_provider = options.sttProvider
    if (options?.sttModel) body.stt_model = options.sttModel
    if (options?.sttCredentialId !== undefined) {
      body.stt_credential_id = options.sttCredentialId
    }
    if (options?.transcribeOverwrite) {
      body.transcribe_overwrite = true
    }
    if (options?.transcribeMode) {
      body.transcribe_mode = options.transcribeMode
    }
    if (options?.diarizationLlmProvider) {
      body.diarization_llm_provider = options.diarizationLlmProvider
    }
    if (options?.diarizationLlmModel) {
      body.diarization_llm_model = options.diarizationLlmModel
    }
    if (options?.diarizationLlmCredentialId !== undefined) {
      body.diarization_llm_credential_id = options.diarizationLlmCredentialId
    }
    if (options?.diarizationPrompt !== undefined) {
      body.diarization_prompt = options.diarizationPrompt
    }
    if (
      options?.provider !== undefined ||
      options?.telephonyIntegrationId !== undefined
    ) {
      body.provider = options.provider ?? null
      body.telephony_integration_id = options.telephonyIntegrationId ?? null
    }
    if (options?.metricIds && options.metricIds.length > 0) {
      body.metric_ids = options.metricIds
    }
    if (options?.includeCompleted) {
      body.include_completed = true
    }
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/retry`,
      body,
    )
    return response.data
  }

  /**
   * Re-enqueue a single failed evaluation row. Returns the refreshed
   * row so the UI can flip the badge to ``pending`` immediately
   * without waiting for the next polling tick. Server returns 409 if
   * the row is still in progress or already completed.
   */
  async retryCallImportEvaluationRow(
    callImportId: string,
    evaluationId: string,
    evalRowId: string,
  ): Promise<CallImportEvaluationRow> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/rows/${evalRowId}/retry`,
    )
    return response.data
  }

  /**
   * Abort an entire in-flight (or queued) evaluation run.
   *
   * Idempotent — calling on a run whose rows are already terminal
   * returns the run unchanged so the UI can wire this to an "Abort
   * run" button without pre-checking state. The backend flips every
   * cancellable row's ``status`` to ``failed`` and stamps
   * ``"Evaluation cancelled by user"`` as the error so the polling UI
   * surfaces the cancel on the next tick. Pairs with the worker's
   * cancellation guard which prevents a late-finishing task from
   * overwriting the cancelled state.
   */
  async cancelCallImportEvaluation(
    callImportId: string,
    evaluationId: string,
  ): Promise<CallImportEvaluationBulkActionResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/cancel`,
    )
    return response.data
  }

  /**
   * Force-fail only rows currently in ``pending`` for an evaluation run.
   *
   * Unlike ``cancelCallImportEvaluation``, this does NOT touch rows that
   * are already ``running``. Useful when queued rows are stuck indefinitely
   * but active workers should keep progressing.
   */
  async forceFailCallImportEvaluationPending(
    callImportId: string,
    evaluationId: string,
  ): Promise<CallImportEvaluationBulkActionResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/force-fail-pending`,
    )
    return response.data
  }

  /**
   * Abort an in-flight (or queued) evaluation for a single row.
   *
   * Mirrors :func:`cancelCallImportEvaluation` but scoped to one row,
   * intended for the per-row Stop button on the evaluation detail
   * rows table. The parent run's counters are rolled up server-side
   * so the run-level pill updates on the same response.
   */
  async cancelCallImportEvaluationRow(
    callImportId: string,
    evaluationId: string,
    evalRowId: string,
  ): Promise<CallImportEvaluationRow> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/rows/${evalRowId}/cancel`,
    )
    return response.data
  }

  async listCallImportEvaluations(callImportId: string): Promise<CallImportEvaluationListResponse> {
    const response = await this.client.get(`/api/v1/call-imports/${callImportId}/evaluations`)
    return response.data
  }

  async getCallImportEvaluation(
    callImportId: string,
    evaluationId: string,
  ): Promise<CallImportEvaluation> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}`,
    )
    return response.data
  }

  async listCallImportEvaluationRows(
    callImportId: string,
    evaluationId: string,
    params: {
      page?: number
      page_size?: number
      q?: string
      metric_id?: string
      metric_value?: string
      classification_yes_no?: string
      classification_choice?: string
      classification_level?: string
      status?: string
      // Flow-chart drilldown: filter to rows whose sequence under the
      // given parent contains ``flow_node`` (and optionally is
      // immediately followed by ``flow_edge_target`` for edge clicks).
      // Accepts a child UUID, a ``disc:<slug>`` discovered id, or a
      // raw slug.
      flow_parent_id?: string
      flow_node?: string
      flow_edge_target?: string
      // Discovered-label filters: either pin to a specific discovered
      // slug or surface every row that produced any candidate under
      // ``discovered_parent_id``.
      discovered_parent_id?: string
      discovered_label_key?: string
      has_discovered?: boolean
      // Column-click sorting from the UI. ``sort_by`` is either a
      // built-in column key (``row_index`` / ``conversation_id`` /
      // ``status``) or ``metric:<metric_uuid>`` for per-metric value
      // sorting; ``sort_dir`` is ``asc`` (default) or ``desc``.
      sort_by?: string
      sort_dir?: 'asc' | 'desc'
    } = {},
  ): Promise<CallImportEvaluationRowListResponse> {
    const cleaned: Record<string, any> = {}
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') cleaned[k] = v
    }
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/rows`,
      { params: cleaned },
    )
    return response.data
  }

  async getCallImportEvaluationRow(
    callImportId: string,
    evaluationId: string,
    rowId: string,
  ): Promise<CallImportEvaluationRow> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/rows/${rowId}`,
    )
    return response.data
  }

  async startCallImportEvaluationExport(
    callImportId: string,
    evaluationId: string,
    format: 'csv' | 'xlsx' = 'csv',
    includeTranscripts = true,
  ): Promise<CallImportEvaluationExportJob> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/export`,
      { format, include_transcripts: includeTranscripts },
    )
    return response.data
  }

  async getCallImportEvaluationExport(
    callImportId: string,
    evaluationId: string,
    jobId: string,
  ): Promise<CallImportEvaluationExportJob> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/export-jobs/${jobId}`,
    )
    return response.data
  }

  async generateCallImportEvaluationPdfReport(
    callImportId: string,
    evaluationId: string,
    vendorName: string,
    reportType: 'external' | 'internal',
    includeWeeklyDelta = false,
    options?: {
      internalBrandImageId?: string | null
      externalBrandImageId?: string | null
      useCase?: string | null
      baselineEvaluationId?: string | null
      reportConfig?: Record<string, any>
      platformBaseUrl?: string | null
    },
  ): Promise<CallImportEvaluationPdfReport | Blob> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/pdf-report`,
      {
        vendor_name: vendorName,
        report_type: reportType,
        include_weekly_delta: includeWeeklyDelta,
        include_period_delta: includeWeeklyDelta,
        baseline_evaluation_id: options?.baselineEvaluationId || null,
        use_case: options?.useCase || null,
        internal_brand_image_id: options?.internalBrandImageId || null,
        external_brand_image_id: options?.externalBrandImageId || null,
        report_config: options?.reportConfig || {},
        platform_base_url: options?.platformBaseUrl || null,
      },
      { responseType: 'arraybuffer' },
    )
    const contentType = String(response.headers['content-type'] || '')
    if (contentType.includes('application/pdf')) {
      return new Blob([response.data], { type: 'application/pdf' })
    }
    const text = new TextDecoder().decode(response.data)
    return JSON.parse(text) as CallImportEvaluationPdfReport
  }

  async listCallImportEvaluationPdfReports(
    callImportId: string,
    evaluationId: string,
  ): Promise<CallImportEvaluationPdfReportListResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/pdf-reports`,
    )
    return response.data
  }

  async getCallImportEvaluationPdfReport(
    callImportId: string,
    evaluationId: string,
    reportId: string,
  ): Promise<CallImportEvaluationPdfReport> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/pdf-reports/${reportId}`,
    )
    return response.data
  }

  async downloadCallImportEvaluationPdfReport(
    callImportId: string,
    evaluationId: string,
    reportId: string,
  ): Promise<Blob> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/pdf-reports/${reportId}/download`,
      { responseType: 'blob' },
    )
    return response.data
  }

  async listCallImportEvaluationBaselineCandidates(
    callImportId: string,
    evaluationId: string,
  ): Promise<CallImportEvaluationBaselineCandidatesResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/baseline-candidates`,
    )
    return response.data
  }

  async deleteCallImportEvaluation(callImportId: string, evaluationId: string): Promise<void> {
    await this.client.delete(`/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}`)
  }

  // Call Import Tags endpoints
  async listCallImportTags(): Promise<CallImportTag[]> {
    const response = await this.client.get('/api/v1/call-import-tags')
    return response.data
  }

  async createCallImportTag(payload: {
    name: string
    color?: string | null
  }): Promise<CallImportTag> {
    const response = await this.client.post('/api/v1/call-import-tags', payload)
    return response.data
  }

  async updateCallImportTag(
    tagId: string,
    payload: { name?: string; color?: string | null },
  ): Promise<CallImportTag> {
    const response = await this.client.patch(
      `/api/v1/call-import-tags/${tagId}`,
      payload,
    )
    return response.data
  }

  async deleteCallImportTag(tagId: string): Promise<void> {
    await this.client.delete(`/api/v1/call-import-tags/${tagId}`)
  }
}
