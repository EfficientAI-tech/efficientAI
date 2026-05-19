// API Types matching the backend schemas

export enum EvaluationType {
  ASR = 'asr',
  TTS = 'tts',
}

export enum EvaluationStatus {
  PENDING = 'pending',
  PROCESSING = 'processing',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled',
}

export interface AudioFile {
  id: string
  filename: string
  format: string
  file_size: number
  duration?: number | null
  sample_rate?: number | null
  channels?: number | null
  uploaded_at: string
}

export interface Evaluation {
  id: string
  audio_id: string
  reference_text?: string | null
  evaluation_type: EvaluationType
  model_name?: string | null
  status: EvaluationStatus
  metrics_requested?: string[] | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  error_message?: string | null
}

export interface EvaluationCreate {
  audio_id: string
  reference_text?: string | null
  evaluation_type: EvaluationType
  model_name?: string | null
  metrics?: string[]
}

export interface EvaluationResult {
  evaluation_id: string
  status: EvaluationStatus
  transcript?: string | null
  metrics: Record<string, any>
  processing_time?: number | null
  model_used?: string | null
  created_at: string
}

export interface BatchEvaluationResult {
  processed_files: number
  failed_files: number
  aggregated_metrics?: Record<string, any> | null
  individual_results: EvaluationResult[]
}

export interface APIKey {
  id: string
  key: string
  name?: string | null
  is_active: boolean
  created_at: string
  last_used?: string | null
  message?: string
}

export interface MessageResponse {
  message: string
}

// IAM & User Types
export enum Role {
  READER = 'reader',
  WRITER = 'writer',
  ADMIN = 'admin',
}

export enum InvitationStatus {
  PENDING = 'pending',
  ACCEPTED = 'accepted',
  DECLINED = 'declined',
  EXPIRED = 'expired',
}

export interface User {
  id: string
  email: string
  name?: string | null
  is_active: boolean
  created_at: string
}

export interface OrganizationMember {
  id: string
  user_id: string
  organization_id: string
  role: Role
  joined_at: string
  user: User
}

export interface Invitation {
  id: string
  organization_id: string
  email: string
  role: Role
  status: InvitationStatus
  expires_at: string
  created_at: string
  organization_name?: string | null
}

export interface InvitationCreate {
  email: string
  role: Role
}

export interface RoleUpdate {
  role: Role
}

export interface Profile {
  id: string
  email: string
  name?: string | null
  first_name?: string | null
  last_name?: string | null
  created_at: string
  organizations: Array<{
    id: string
    name: string
    role: string
    joined_at: string
  }>
}

export interface UserUpdate {
  name?: string | null
  first_name?: string | null
  last_name?: string | null
  email?: string | null
}

export interface UserPreferences {
  theme?: string
  notifications_enabled?: boolean
  email_notifications?: boolean
  default_language?: string
  [key: string]: any
}

export interface UserPreferencesUpdate {
  theme?: string
  notifications_enabled?: boolean
  email_notifications?: boolean
  default_language?: string
  [key: string]: any
}

// Integration Types
export enum IntegrationPlatform {
  RETELL = 'retell',
  VAPI = 'vapi',
  CARTESIA = 'cartesia',
  ELEVENLABS = 'elevenlabs',
  DEEPGRAM = 'deepgram',
  MURF = 'murf',
  SARVAM = 'sarvam',
  VOICEMAKER = 'voicemaker',
  SMALLEST = 'smallest',
}

export enum TelephonyProvider {
  PLIVO = 'plivo',
  EXOTEL = 'exotel',
}

export interface Integration {
  id: string
  organization_id: string
  platform: IntegrationPlatform
  name?: string | null
  public_key?: string | null
  is_active: boolean
  /** True if this row is the default credential for (org, platform). */
  is_default?: boolean
  created_at: string
  updated_at: string
  last_tested_at?: string | null
}

export interface IntegrationCreate {
  platform: IntegrationPlatform
  api_key: string
  public_key?: string
  name?: string | null
  /** Mark the new credential as the default for (org, platform). */
  is_default?: boolean
}

// VoiceBundle Types
export enum ModelProvider {
  OPENAI = 'openai',
  ANTHROPIC = 'anthropic',
  GOOGLE = 'google',
  XAI = 'xai',
  COHERE = 'cohere',
  MISTRAL = 'mistral',
  META = 'meta',
  TOGETHER = 'together',
  PERPLEXITY = 'perplexity',
  AZURE = 'azure',
  AWS = 'aws',
  DEEPGRAM = 'deepgram',
  CARTESIA = 'cartesia',
  ELEVENLABS = 'elevenlabs',
  MURF = 'murf',
  CUSTOM = 'custom',
  SARVAM = 'sarvam',
  VOICEMAKER = 'voicemaker',
  SMALLEST = 'smallest',
}

// AI Provider Types
export interface AIProvider {
  id: string
  provider: ModelProvider
  api_key?: string | null
  name?: string | null
  is_active: boolean
  /** True if this row is the default credential for (org, provider). */
  is_default?: boolean
  created_at: string
  updated_at: string
  last_tested_at?: string | null
}

export interface AIProviderCreate {
  provider: ModelProvider
  api_key: string
  name?: string | null
  /** Mark the new credential as the default for (org, provider). */
  is_default?: boolean
}

export interface AIProviderUpdate {
  api_key?: string | null
  name?: string | null
  is_active?: boolean
}

export enum VoiceBundleType {
  STT_LLM_TTS = 'stt_llm_tts',
  S2S = 's2s',
}

export interface VoiceBundle {
  id: string
  name: string
  description?: string | null
  bundle_type: VoiceBundleType
  stt_provider?: ModelProvider | null
  stt_model?: string | null
  /**
   * Optional explicit AIProvider/Integration row id for STT. When null the
   * runtime resolver picks the default credential for stt_provider.
   */
  stt_credential_id?: string | null
  llm_provider?: ModelProvider | null
  llm_model?: string | null
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  llm_config?: Record<string, any> | null
  llm_credential_id?: string | null
  tts_provider?: ModelProvider | null
  tts_model?: string | null
  tts_voice?: string | null
  tts_config?: Record<string, any> | null
  tts_credential_id?: string | null
  s2s_provider?: ModelProvider | null
  s2s_model?: string | null
  s2s_config?: Record<string, any> | null
  s2s_credential_id?: string | null
  extra_metadata?: Record<string, any> | null
  is_active: boolean
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface VoiceBundleCreate {
  name: string
  description?: string | null
  bundle_type?: VoiceBundleType
  stt_provider?: ModelProvider | null
  stt_model?: string | null
  stt_credential_id?: string | null
  llm_provider?: ModelProvider | null
  llm_model?: string | null
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  llm_config?: Record<string, any> | null
  llm_credential_id?: string | null
  tts_provider?: ModelProvider | null
  tts_model?: string | null
  tts_voice?: string | null
  tts_config?: Record<string, any> | null
  tts_credential_id?: string | null
  s2s_provider?: ModelProvider | null
  s2s_model?: string | null
  s2s_config?: Record<string, any> | null
  s2s_credential_id?: string | null
  extra_metadata?: Record<string, any> | null
}

// Test Agent Types
export interface TestAgent {
  id: string
  agent_id?: string | null
  name: string
  phone_number?: string | null
  telephony_phone_number_id?: string | null
  language: string
  description: string | null
  call_type: string
  call_medium: string
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
  voice_ai_agent_id?: string | null
  created_at: string
  updated_at: string
}

// Test Agent Conversation Types
export interface TestAgentConversation {
  id: string
  organization_id: string
  agent_id: string
  persona_id: string
  scenario_id: string
  voice_bundle_id: string
  status: string
  live_transcription?: Array<{
    speaker: string
    text: string
    timestamp: number
    audio_segment_key?: string
  }> | null
  conversation_audio_key?: string | null
  full_transcript?: string | null
  started_at: string
  ended_at?: string | null
  duration_seconds?: number | null
  conversation_metadata?: Record<string, any> | null
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface TestAgentConversationCreate {
  agent_id: string
  persona_id: string
  scenario_id: string
  voice_bundle_id: string
  conversation_metadata?: Record<string, any> | null
}

export interface TestAgentConversationUpdate {
  status?: string | null
  live_transcription?: Array<Record<string, any>> | null
  full_transcript?: string | null
  conversation_metadata?: Record<string, any> | null
}

export interface VoiceBundleUpdate {
  name?: string
  description?: string | null
  stt_provider?: ModelProvider
  stt_model?: string
  stt_credential_id?: string | null
  llm_provider?: ModelProvider
  llm_model?: string
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  llm_config?: Record<string, any> | null
  llm_credential_id?: string | null
  tts_provider?: ModelProvider
  tts_model?: string
  tts_voice?: string | null
  tts_config?: Record<string, any> | null
  tts_credential_id?: string | null
  s2s_provider?: ModelProvider | null
  s2s_model?: string | null
  s2s_config?: Record<string, any> | null
  s2s_credential_id?: string | null
  extra_metadata?: Record<string, any> | null
  is_active?: boolean
}

// Data Sources Types
export interface S3ConnectionTest {
  bucket_name: string
  region?: string
  access_key_id: string
  secret_access_key: string
  endpoint_url?: string | null
}

export interface S3ConnectionTestResponse {
  success: boolean
  message: string
  bucket_name?: string | null
}

export interface S3FileInfo {
  key: string
  filename: string
  size: number
  last_modified: string
}

export interface S3FolderInfo {
  name: string
  path: string
}

export interface S3ListFilesResponse {
  files: S3FileInfo[]
  total: number
  prefix?: string | null
}

export interface S3BrowseResponse {
  folders: S3FolderInfo[]
  files: S3FileInfo[]
  current_path: string
  organization_id: string
}

export interface S3Status {
  enabled: boolean
  error?: string | null
}

// Alert Types
export enum AlertMetricType {
  NUMBER_OF_CALLS = 'number_of_calls',
  CALL_DURATION = 'call_duration',
  ERROR_RATE = 'error_rate',
  SUCCESS_RATE = 'success_rate',
  LATENCY = 'latency',
  CUSTOM = 'custom',
}

export enum AlertAggregation {
  SUM = 'sum',
  AVG = 'avg',
  COUNT = 'count',
  MIN = 'min',
  MAX = 'max',
}

export enum AlertOperator {
  GREATER_THAN = '>',
  LESS_THAN = '<',
  GREATER_THAN_OR_EQUAL = '>=',
  LESS_THAN_OR_EQUAL = '<=',
  EQUAL = '=',
  NOT_EQUAL = '!=',
}

export enum AlertNotifyFrequency {
  IMMEDIATE = 'immediate',
  HOURLY = 'hourly',
  DAILY = 'daily',
  WEEKLY = 'weekly',
}

export enum AlertStatus {
  ACTIVE = 'active',
  PAUSED = 'paused',
  DISABLED = 'disabled',
}

export enum AlertHistoryStatus {
  TRIGGERED = 'triggered',
  NOTIFIED = 'notified',
  ACKNOWLEDGED = 'acknowledged',
  RESOLVED = 'resolved',
}

export interface Alert {
  id: string
  organization_id: string
  name: string
  description?: string | null
  metric_type: AlertMetricType
  aggregation: AlertAggregation
  operator: AlertOperator
  threshold_value: number
  time_window_minutes: number
  agent_ids?: string[] | null
  notify_frequency: AlertNotifyFrequency
  notify_emails?: string[] | null
  notify_webhooks?: string[] | null
  status: AlertStatus
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface AlertCreate {
  name: string
  description?: string | null
  metric_type?: AlertMetricType
  aggregation?: AlertAggregation
  operator?: AlertOperator
  threshold_value: number
  time_window_minutes?: number
  agent_ids?: string[] | null
  notify_frequency?: AlertNotifyFrequency
  notify_emails?: string[]
  notify_webhooks?: string[]
}

export interface AlertUpdate {
  name?: string
  description?: string | null
  metric_type?: AlertMetricType
  aggregation?: AlertAggregation
  operator?: AlertOperator
  threshold_value?: number
  time_window_minutes?: number
  agent_ids?: string[] | null
  notify_frequency?: AlertNotifyFrequency
  notify_emails?: string[]
  notify_webhooks?: string[]
  status?: AlertStatus
}

export interface AlertHistoryItem {
  id: string
  organization_id: string
  alert_id: string
  triggered_at: string
  triggered_value: number
  threshold_value: number
  status: AlertHistoryStatus
  notified_at?: string | null
  notification_details?: Record<string, any> | null
  acknowledged_at?: string | null
  acknowledged_by?: string | null
  resolved_at?: string | null
  resolved_by?: string | null
  resolution_notes?: string | null
  context_data?: Record<string, any> | null
  created_at: string
  updated_at: string
  alert?: Alert
}


// Cron Job Types
export enum CronJobStatus {
  ACTIVE = 'active',
  PAUSED = 'paused',
  COMPLETED = 'completed',
}

export interface CronJob {
  id: string
  organization_id: string
  name: string
  cron_expression: string
  timezone: string
  max_runs: number
  current_runs: number
  evaluator_ids: string[]
  status: CronJobStatus
  next_run_at?: string | null
  last_run_at?: string | null
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface CronJobCreate {
  name: string
  cron_expression: string
  timezone: string
  max_runs: number
  evaluator_ids: string[]
}

export interface CronJobUpdate {
  name?: string
  cron_expression?: string
  timezone?: string
  max_runs?: number
  evaluator_ids?: string[]
  status?: CronJobStatus
}

// --- Call Imports ---

export type CallImportStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'partial'
  | 'failed'

export type CallImportRowStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'

/** Where the value in `transcript` came from. */
export type CallImportTranscriptSource =
  | 'csv'
  | 'transcribed'
  | 'edited'
  | null
/** Lifecycle status for the post-hoc transcription workflow itself. */
export type CallImportTranscriptStatus =
  | 'idle'
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | null

/**
 * Which transcript an evaluation run scored against.
 *  - `production`: the CSV-supplied value on `CallImportRow.transcript`.
 *  - `diarised`: the worker-produced value on `CallImportRow.diarised_transcript`.
 */
export type CallImportEvaluationTranscriptSource = 'production' | 'diarised'

export interface CallImportRow {
  id: string
  row_index: number
  external_call_id: string
  recording_url: string | null
  /** Production transcript — the value supplied via the CSV upload. */
  transcript: string | null
  /** Provenance of the stored production transcript (csv = CSV upload, edited = manual edit). */
  transcript_source: CallImportTranscriptSource
  /** Legacy: provider recorded by the original transcription worker before the split. */
  transcript_provider: string | null
  transcript_model: string | null
  transcript_status: CallImportTranscriptStatus
  transcript_error: string | null
  transcribed_at: string | null
  /** Diarised transcript — produced by the post-hoc diarisation worker. */
  diarised_transcript: string | null
  /** Provider used by the diarisation worker (e.g. "deepgram"). */
  diarised_transcript_provider: string | null
  diarised_transcript_model: string | null
  diarised_transcript_status: CallImportTranscriptStatus
  diarised_transcript_error: string | null
  diarised_at: string | null
  raw_columns: Record<string, string> | null
  status: CallImportRowStatus
  recording_s3_key: string | null
  recording_content_type: string | null
  recording_size_bytes: number | null
  error_message: string | null
  attempts: number
  created_at: string
  updated_at: string
}

export interface CallImportTag {
  id: string
  name: string
  color: string | null
  created_at: string
  updated_at: string
}

/**
 * In-org Workspace - the active workspace scopes call imports and
 * metrics in the UI. The org's Default workspace is auto-seeded by
 * migration 033 and cannot be deleted.
 */
export interface Workspace {
  id: string
  organization_id: string
  name: string
  slug: string
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface CallImport {
  id: string
  organization_id: string
  /** Workspace this import belongs to. */
  workspace_id: string
  provider: string
  telephony_integration_id: string | null
  original_filename: string | null
  /**
   * For Excel uploads, which worksheet this batch came from. ``null``
   * for CSV uploads (CSV files have no sheet concept) and for any
   * imports created before multi-sheet support landed.
   */
  sheet_name: string | null
  /** Optional free-text dataset label (high-level segregation filter). */
  dataset: string | null
  /** Tags currently attached to this import. Empty array if untagged. */
  tags: CallImportTag[]
  column_mapping: Record<string, string | null>
  extra_columns: string[]
  custom_column_mapping: Record<string, string>
  total_rows: number
  completed_rows: number
  failed_rows: number
  status: CallImportStatus
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface CallImportDetail extends CallImport {
  rows: CallImportRow[]
  /**
   * Total row count *after* applying the optional ``q`` search filter.
   * ``null`` when no filter is active — paginate against ``total_rows``
   * in that case.
   */
  filtered_total_rows: number | null
}

export interface CallImportListResponse {
  items: CallImport[]
  total: number
  page: number
  page_size: number
}

export interface CallImportUploadResponse {
  id: string
  total_rows: number
  status: CallImportStatus
  dataset: string | null
  tags: CallImportTag[]
  message: string
}

/** One worksheet (or one CSV file synthesized as a single sheet). */
export interface CallImportPreviewSheet {
  /** Sheet name for xlsx; filename for csv. */
  name: string
  /** Column headers from the first non-empty row. */
  headers: string[]
  /** Approximate count of data rows (excludes the header row). */
  row_count: number
}

/**
 * Sheets / headers extracted server-side from an uploaded CSV or Excel
 * workbook. Drives the modal's column-mapping UI without forcing the
 * frontend to parse the file itself.
 */
export interface CallImportPreviewResponse {
  /** ``'csv'`` or ``'xlsx'``. */
  format: 'csv' | 'xlsx'
  sheets: CallImportPreviewSheet[]
}

export type MetricSelectionMode = 'single_choice' | 'multi_label'

export interface CallImportMetricSummary {
  id: string
  name: string
  metric_type: string | null
  description: string | null
  parent_metric_id?: string | null
  selection_mode?: MetricSelectionMode | null
  /** Only meaningful on multi_label parents; gates the Discovered
   *  Labels panel on the Flow tab. Defaults to false. */
  allow_discovery?: boolean
}

/** Per-metric LLM override (provider+model+optional credential). */
export interface CallImportEvaluationLLMOverride {
  provider?: string | null
  model?: string | null
  credential_id?: string | null
}

export interface CallImportEvaluation {
  id: string
  call_import_id: string
  organization_id: string
  /** User-supplied label for the run; null when not named. */
  name: string | null
  selected_metric_ids: string[]
  /** parent_id -> [child_id, ...] snapshot captured at run time. */
  selected_metric_groups?: Record<string, string[]> | null
  metrics: CallImportMetricSummary[]
  status: 'pending' | 'running' | 'completed' | 'partial' | 'failed'
  total_rows: number
  completed_rows: number
  failed_rows: number
  error_message: string | null
  /** Run-level LLM provider chosen by the user (null = legacy default). */
  llm_provider: string | null
  llm_model: string | null
  llm_credential_id: string | null
  metric_llm_overrides: Record<string, CallImportEvaluationLLMOverride> | null
  stt_provider: string | null
  stt_model: string | null
  stt_credential_id: string | null
  /**
   * Which transcript column this run scored against.
   * Defaults to `production` on legacy runs.
   */
  transcript_source: CallImportEvaluationTranscriptSource
  /**
   * Other evaluation ids created in the same Run Evaluation request.
   * Populated only on the POST response when the user ticked both
   * Production and Diarised. Empty array on all other reads.
   */
  sibling_evaluation_ids: string[]
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  /**
   * Cached LLM-generated TLDR rendered above the Visualizations tab.
   * Populated lazily via ``POST /evaluations/{id}/insights``; null on
   * runs the user has not summarised yet.
   */
  tldr_summary?: EvaluationTldrSummary | null
}

/**
 * LLM-generated narrative + bullet patterns for a single evaluation
 * run. Cached on the evaluation row so re-opening the Visualizations
 * tab doesn't auto-burn LLM tokens. ``is_stale`` is computed by the
 * backend at read time when ``completed_rows`` has grown since the
 * summary was generated.
 */
export interface EvaluationTldrSummary {
  narrative: string
  patterns: string[]
  generated_at: string
  generated_at_completed_rows: number
  provider?: string | null
  model?: string | null
  is_stale: boolean
}

export interface CallImportEvaluationListResponse {
  items: CallImportEvaluation[]
  total: number
}

export interface CallImportEvaluationRow {
  id: string
  evaluation_id: string
  call_import_row_id: string
  row_index: number | null
  external_call_id: string | null
  transcript: string | null
  raw_columns: Record<string, any> | null
  recording_url: string | null
  /**
   * S3 object key for the downloaded recording. Prefer this over
   * ``recording_url`` for playback — we resolve it to a presigned URL
   * so audio plays from our storage instead of the (often expired)
   * provider URL.
   */
  recording_s3_key: string | null
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  metric_scores: Record<string, any>
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface CallImportEvaluationRowListResponse {
  items: CallImportEvaluationRow[]
  total: number
  page: number
  page_size: number
}

// --- Diarization / transcription ---

export interface CallImportTranscribeRequest {
  stt_provider: string
  stt_model: string
  credential_id?: string | null
  language?: string | null
  only_missing?: boolean
  overwrite_existing?: boolean
  row_ids?: string[]
}

export interface CallImportTranscribeResponse {
  queued: number
  skipped_rows: number
  skipped_reason_counts: Record<string, number>
}

// --- Aggregation / visualization payloads ---

export interface CallImportMetricHistogramBucket {
  x0: number
  x1: number
  count: number
}

export interface CallImportMetricValueCount {
  label: string
  count: number
}

export interface CallImportMetricAggregate {
  metric_id: string
  metric_name: string
  metric_type: string | null
  /**
   * True when the metric is a multi-label classifier parent.
   * ``value_counts`` then lists per-child label tallies and one row
   * may contribute to several labels, so the chart layout has to
   * ignore the pie toggle (slices wouldn't sum to 100%) and the
   * n-badge represents rows scored, not label occurrences.
   */
  is_multi_label_parent?: boolean
  count: number
  skipped_count: number
  error_count: number
  mean: number | null
  median: number | null
  p25: number | null
  p75: number | null
  p95: number | null
  min: number | null
  max: number | null
  stddev: number | null
  histogram_buckets: CallImportMetricHistogramBucket[]
  value_counts: CallImportMetricValueCount[]
}

export interface CallImportEvaluationAggregateResponse {
  evaluation_id: string
  total_rows: number
  completed_rows: number
  failed_rows: number
  metrics: CallImportMetricAggregate[]
}

export interface CallImportInsightsRunPoint {
  evaluation_id: string
  name: string | null
  created_at: string
  mean: number | null
  completed_rows: number
}

export interface CallImportInsightsMetric {
  metric_id: string
  metric_name: string
  metric_type: string | null
  latest: CallImportMetricAggregate | null
  trend: CallImportInsightsRunPoint[]
}

export interface CallImportInsightsResponse {
  call_import_id: string
  total_rows: number
  rows_with_transcript: number
  rows_without_transcript: number
  transcript_source_counts: Record<string, number>
  evaluation_count: number
  metrics: CallImportInsightsMetric[]
}

// --- Metrics hierarchy + flow visualization ---

export interface MetricSummary {
  id: string
  organization_id: string
  name: string
  description: string | null
  metric_type: string
  trigger: string
  enabled: boolean
  is_default: boolean
  metric_origin: string
  supported_surfaces: string[]
  enabled_surfaces: string[]
  custom_data_type: string | null
  custom_config: Record<string, any> | null
  tags: string[] | null
  capture_rationale: boolean
  parent_metric_id: string | null
  selection_mode: MetricSelectionMode | null
  allow_discovery?: boolean
  /**
   * CSV header names this metric reads from a call import row's
   * ``raw_columns`` JSON. Empty array (the default) means the metric
   * scores the transcript like before; a non-empty list switches the
   * metric to a "column-input judge" at evaluation time.
   */
  input_columns?: string[]
  /**
   * When true, this metric is a "transcript-compare judge": at
   * call-import evaluation time the worker feeds BOTH the production
   * transcript and the diarised transcript to the LLM as a labeled
   * pair, and the run's transcript_source toggle is ignored for this
   * metric. Mutually exclusive with input_columns, parent_metric_id
   * and selection_mode — v1 keeps comparison metrics standalone.
   */
  compare_transcripts?: boolean
  children?: MetricSummary[]
  created_at: string
  updated_at: string
  created_by: string | null
}

export interface MetricChildDraft {
  name: string
  description?: string | null
  enabled?: boolean
  capture_rationale?: boolean | null
  tags?: string[] | null
}

export interface MetricCreateWithChildrenPayload {
  name: string
  description?: string | null
  selection_mode: MetricSelectionMode
  enabled?: boolean
  supported_surfaces?: string[]
  enabled_surfaces?: string[]
  tags?: string[] | null
  allow_discovery?: boolean
  children: MetricChildDraft[]
}

export interface MetricFlowNode {
  id: string
  label: string
  count: number
  is_terminal: boolean
  is_discovered?: boolean
}

export interface MetricFlowEdge {
  source: string
  target: string
  count: number
}

export interface MetricFlowResponse {
  parent_metric_id: string
  parent_metric_name: string
  selection_mode: MetricSelectionMode | null
  nodes: MetricFlowNode[]
  edges: MetricFlowEdge[]
  total_rows: number
  rows_with_sequence: number
}

export interface DiscoveredLabel {
  key: string
  name: string
  description?: string | null
  sample_rationale?: string | null
  /**
   * Up to 3 distinct LLM rationales captured for this candidate
   * across rows. The Discovered Labels promote flow surfaces the
   * first 2 as an ``Examples:`` block on the new sub-metric's
   * rubric so the user starts with concrete cases in the prompt.
   */
  examples?: string[]
  count: number
}

export interface DiscoveredLabelsResponse {
  parent_metric_id: string
  items: DiscoveredLabel[]
}
