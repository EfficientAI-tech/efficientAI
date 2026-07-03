// API Types matching the backend schemas

export type { LLMGenerationConfig } from '../config/llmGenerationParams'
import type { LLMGenerationConfig } from '../config/llmGenerationParams'

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

export interface DashboardSummary {
  evaluations: {
    total: number
    completed: number
    pending: number
    failed: number
  }
  resources: {
    agents: number
    personas: number
    scenarios: number
    integrations: number
    voice_bundles: number
  }
  setup_progress: {
    has_integration: boolean
    has_voice_bundle: boolean
    has_agent: boolean
    has_evaluation: boolean
  }
  metrics: {
    total: number
    enabled: number
  }
  call_imports: {
    total: number
  }
  call_import_evaluations: {
    total: number
    completed: number
    running: number
    failed: number
  }
  recent_evaluations: Evaluation[]
}

export interface ModelConfigEntry {
  provider: string
  model_type: string
  description?: string
  featured?: boolean
  featured_rank?: number
  highlights?: string[]
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
  FIREWORKS = 'fireworks',
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
  /** True when provider secrets are resolved by the Bifrost gateway. */
  gateway_managed?: boolean
  created_at: string
  updated_at: string
  last_tested_at?: string | null
}

export interface AIProviderCreate {
  provider: ModelProvider
  api_key?: string | null
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
  provider?: 's3' | 'gcs' | string
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

/**
 * Lifecycle for a call-import batch.
 *
 *  - ``uploaded``   : file landed in S3, no mapping yet.
 *  - ``mapped``     : user picked a schema + sheet + column mapping; no
 *                     rows materialised yet, no worker enqueued.
 *  - ``processing`` : rows materialised + workers enqueued.
 *  - ``pending``    : transient state used by the legacy one-shot
 *                     ``POST /upload`` endpoint just before transitioning
 *                     to ``processing``.
 */
export type CallImportStatus =
  | 'pending'
  | 'uploaded'
  | 'mapped'
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

/**
 * One contiguous turn inside ``CallImportRow.diarised_segments``.
 *
 * The diarisation worker rewrites each pyannote ``Speaker N`` label
 * into ``agent`` / ``user`` (first speaker = agent heuristic). Anything
 * beyond two distinct speakers keeps a generic ``speaker_N`` label so
 * multi-party recordings still render every voice.
 */
export interface CallImportDiarisedSegment {
  speaker: string
  text: string
  start: number
  end: number
  /** Original pyannote label (``Speaker 1`` / ``Speaker 2`` / ...). */
  raw_speaker: string
}

export interface CallImportRow {
  id: string
  row_index: number
  /** Mandatory identifier per row. Renamed from ``external_call_id``. */
  conversation_id: string
  recording_url: string | null
  recording_date: string | null
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
  /**
   * Structured speaker turns produced by the diarisation worker. Each
   * entry is a single contiguous turn shaped as
   * `{ speaker: 'agent' | 'user' | 'speaker_N', text, start, end,
   *   raw_speaker }`. ``diarised_transcript`` is a rendered
   * `<speaker>: <text>` view of this list with
   * ``diarised_speaker_swap`` applied. ``null`` on legacy rows that
   * were diarised before structured turns were persisted (or when the
   * STT provider didn't surface segments).
   */
  diarised_segments: CallImportDiarisedSegment[] | null
  /**
   * When ``true`` the ``agent`` <-> ``user`` mapping inside
   * ``diarised_segments`` is inverted in the rendered transcript /
   * CSV export. The worker writes the canonical mapping using a
   * "first speaker is the agent" heuristic; reviewers can flip the
   * toggle from the row detail panel without re-running diarisation.
   */
  diarised_speaker_swap: boolean
  /**
   * LLM that turned the STT plain-text output into structured
   * ``diarised_segments``. NULL on legacy rows (pre-LLM-diariser).
   */
  diarised_llm_provider: string | null
  diarised_llm_model: string | null
  /**
   * Exact prompt the LLM diariser ran with. Useful for the modal to
   * pre-fill its textarea when the operator wants to iterate on a
   * previously-diarised row.
   */
  diarised_prompt: string | null
  /**
   * Diarisation pipeline that produced this row's turns.
   * - `stt_llm` (default) — two-stage STT then LLM diariser.
   * - `llm_only` — single-stage multimodal LLM (audio in).
   * Read-only; written by the worker on each diarisation.
   */
  transcribe_mode?: 'stt_llm' | 'llm_only'
  /**
   * Per-row preservation of the mapped source cells. Values land here
   * as whatever type the schema parameter coerced them to —
   * strings (text / url / conversation_id / recording_url /
   * recording_date / transcript / datetime), numbers, booleans, or
   * ``null`` for blanks. Always
   * coerce with ``String(value)`` before string operations.
   */
  raw_columns: Record<string, string | number | boolean | null> | null
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
 * Parameter type tag on a Call Import schema parameter.
 *
 *  - ``conversation_id``: mandatory identifier (one per schema).
 *  - ``recording_url``: feeds ``CallImportRow.recording_url``.
 *  - ``recording_date``: date-only call recording date used for reports.
 *  - ``transcript``: feeds ``CallImportRow.transcript``.
 *  - ``text`` / ``number`` / ``boolean`` / ``datetime`` / ``url``:
 *    generic typed fields preserved per row in ``raw_columns`` and
 *    surfaced in the evaluation export under the parameter's name.
 */
export type CallImportSchemaParameterType =
  | 'conversation_id'
  | 'recording_url'
  | 'recording_date'
  | 'transcript'
  | 'text'
  | 'number'
  | 'boolean'
  | 'datetime'
  | 'url'

export interface CallImportSchemaParameter {
  id?: string
  name: string
  type: CallImportSchemaParameterType
  description: string | null
  is_required: boolean
  ordering?: number
}

export interface CallImportSchema {
  id: string
  organization_id: string
  workspace_id: string
  name: string
  description: string | null
  parameters: CallImportSchemaParameter[]
  /** How many CallImport batches reference this schema. */
  usage_count: number
  created_at: string
  updated_at: string
}

export interface CallImportSchemaListResponse {
  items: CallImportSchema[]
  total: number
}

export interface CallImportSchemaCreate {
  name: string
  description?: string | null
  parameters: Array<Omit<CallImportSchemaParameter, 'id' | 'ordering'>>
}

export interface CallImportSchemaUpdate {
  name?: string
  description?: string | null
  parameters?: Array<Omit<CallImportSchemaParameter, 'id' | 'ordering'>>
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
  role_id?: string | null
  role_name?: string | null
  capabilities?: string[]
}

export interface WorkspaceRole {
  id: string
  organization_id: string
  name: string
  description?: string | null
  capabilities: string[]
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface WorkspaceMember {
  id: string
  workspace_id: string
  user_id: string
  role_id: string
  role_name: string
  user_email: string
  user_name?: string | null
  added_by_user_id?: string | null
  created_at: string
}

export interface CapabilityInfo {
  key: string
  label: string
}

export interface CapabilityDomain {
  key: string
  label: string
  capabilities: CapabilityInfo[]
}

export interface WorkspaceRoleCreate {
  name: string
  description?: string | null
  capabilities: string[]
}

export interface WorkspaceRoleUpdate {
  name?: string
  description?: string | null
  capabilities?: string[]
}

export interface CallImport {
  id: string
  organization_id: string
  /** Workspace this import belongs to. */
  workspace_id: string
  /**
   * Telephony provider key. ``null`` until the IMPORT stage in the
   * staged flow (which is the first step that knows the provider).
   * Always populated on post-import batches and on legacy one-shot
   * uploads.
   */
  provider: string | null
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
  /**
   * Reusable Input Parameter schema the batch was uploaded against.
   * NULL on legacy batches uploaded before the schema-driven flow shipped.
   */
  schema_id: string | null
  /**
   * Schema-driven mapping: ``{parameter_name: csv_header}``. Empty on
   * legacy batches; check ``column_mapping`` / ``extra_columns`` /
   * ``custom_column_mapping`` instead for those.
   */
  parameter_mapping: Record<string, string>
  /** Legacy free-form mapping kept for batches uploaded before schemas. */
  column_mapping: Record<string, string | null>
  /** Legacy extra-column list kept for backwards-compat. */
  extra_columns: string[]
  /** Legacy uploader-named columns kept for backwards-compat. */
  custom_column_mapping: Record<string, string>
  /**
   * Source headers the uploader explicitly skipped, captured at the
   * MAP stage. Empty for legacy one-shot uploads where the value was
   * ephemeral.
   */
  skipped_columns: string[]
  /** S3 key for the staged source file. ``null`` on legacy batches. */
  source_s3_key: string | null
  /** ``'csv'`` / ``'xlsx'`` for staged files, or ``'audio'`` for manual uploads. */
  source_format: string | null
  source_size_bytes: number | null
  source_content_type: string | null
  /**
   * Snapshot of the file's sheets + headers captured at UPLOAD time so
   * the MAP UI can render without re-fetching the source from S3.
   * ``null`` on legacy batches.
   */
  available_sheets: CallImportPreviewSheet[] | null
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
  /**
   * Batch-wide aggregates of ``CallImportRow.diarised_transcript_status``.
   * The ``idle`` bucket (rows never touched by the transcribe/diarise
   * worker) is implicit: ``total_rows - (pending + running + completed
   * + failed)``. Lets the UI render a transcribe-and-diarise progress
   * bar without paginating through every row.
   */
  diarised_pending_rows: number
  diarised_running_rows: number
  diarised_completed_rows: number
  diarised_failed_rows: number
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

/** Per-metric LLM override (provider+model+optional credential + generation params). */
export interface CallImportEvaluationLLMOverride {
  provider?: string | null
  model?: string | null
  credential_id?: string | null
  llm_config?: LLMGenerationConfig | null
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
  llm_config?: LLMGenerationConfig | null
  metric_llm_overrides: Record<string, CallImportEvaluationLLMOverride> | null
  stt_provider: string | null
  stt_model: string | null
  stt_credential_id: string | null
  /**
   * Run-level LLM diariser config used when the worker auto-diarises
   * rows that are missing a diarised transcript.
   */
  diarisation_llm_provider?: string | null
  diarisation_llm_model?: string | null
  diarisation_llm_credential_id?: string | null
  diarisation_prompt?: string | null
  /**
   * Diarisation pipeline shape this run was created with.
   * - `stt_llm` (default) — STT then an LLM diariser over the text.
   * - `llm_only` — audio fed directly to a multimodal diariser LLM.
   * Surfaced so the retry / re-run UI can preselect the right mode.
   */
  transcribe_mode?: 'stt_llm' | 'llm_only'
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
  user_insights?: EvaluationUserInsightsState | null
  metric_clusters?: EvaluationMetricClustersState | null
  /**
   * True when the user opted into top-level metric discovery on the
   * Run Evaluation modal. Gates the Discovered metrics panel on the
   * evaluation detail Flow tab.
   */
  discover_new_metrics?: boolean
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
  metric_insights?: Record<string, string>
  generated_at: string
  generated_at_completed_rows: number
  provider?: string | null
  model?: string | null
  is_stale: boolean
}

export interface UserInsightCategory {
  label: string
  count: number
  share_pct: number
}

export interface UserInsightEvidenceTurn {
  speaker: string
  text: string
}

export interface UserInsightEvidence {
  conversation_id?: string | null
  quote: string
  turns?: UserInsightEvidenceTurn[]
}

export interface EvaluationUserInsightItem {
  id: string
  title: string
  categories: UserInsightCategory[]
  observation: string
  evidence: UserInsightEvidence
}

export interface EvaluationUserInsightsState {
  status: 'idle' | 'running' | 'completed' | 'failed'
  insights: EvaluationUserInsightItem[]
  overview?: string | null
  generated_at?: string | null
  generated_at_completed_rows: number
  progress?: { completed_llm_calls: number; total_llm_calls: number } | null
  provider?: string | null
  model?: string | null
  llm_calls_used: number
  max_llm_calls?: number | null
  error_message?: string | null
  is_stale: boolean
}

export type MetricClusterGapLabel =
  | 'LOGIC_GAP'
  | 'UNDERSPEC'
  | 'EXISTS_NO_TRIGGER'
  | 'MISSING'

export interface MetricSubCluster {
  label: string
  count: number
  share_pct: number
}

export interface MetricClusterEvidenceTurn {
  speaker: string
  text: string
}

export interface MetricClusterEvidence {
  conversation_id?: string | null
  evaluation_row_id?: string | null
  quote: string
  turns?: MetricClusterEvidenceTurn[]
}

export interface MetricCluster {
  id: string
  label: string
  gap_label: MetricClusterGapLabel
  level: number
  count: number
  share_pct: number
  sub_clusters: MetricSubCluster[]
  observation: string
  failure_reason?: string
  evidence: MetricClusterEvidence
  is_discovered: boolean
}

export interface MetricClusterGroup {
  metric_id: string
  metric_name: string
  flagged_count: number
  failure_reason?: string
  clusters: MetricCluster[]
}

export interface DiscoveredProblemCluster {
  id: string
  label: string
  gap_label: MetricClusterGapLabel
  count: number
  share_pct: number
  observation: string
  failure_reason?: string
  evidence: MetricClusterEvidence
}

export interface RcaRepeatedPatternRow {
  metric_id: string
  metric_name: string
  top_rca_patterns: string
  evidence_share_pct: number
  evidence_calls: number
  evidence_cluster_count?: number
  failure_reason: string
}

export interface RcaMetricHotspotRow {
  metric_id: string
  metric_name: string
  description: string
  metric_rate_pct: number
  flagged_calls: number
}

export interface RcaPromptAreaRow {
  label: string
  share_pct: number
  gap_label: MetricClusterGapLabel
}

export interface MetricClustersRcaSummary {
  total_clusters: number
  total_clustered_instances: number
  total_flagged_instances?: number
  analysed_calls: number
  repeated_patterns: RcaRepeatedPatternRow[]
  metric_hotspots: RcaMetricHotspotRow[]
  prompt_areas: RcaPromptAreaRow[]
}

export interface MetricFailurePolicy {
  metric_id: string
  failure_values: string[]
  failure_child_names?: string[]
  numeric_rule?: { op: 'lt' | 'lte' | 'gt' | 'gte'; threshold: number } | null
}

export interface MetricFailurePolicyValueCount {
  label: string
  count: number
}

export interface MetricFailurePolicyMetricPreview {
  metric_id: string
  metric_name: string
  metric_type?: string | null
  selection_mode?: string | null
  is_multi_label_parent: boolean
  value_counts: MetricFailurePolicyValueCount[]
  child_names: string[]
  row_count_by_value: Record<string, number>
  suggested_policy: MetricFailurePolicy
  effective_policy: MetricFailurePolicy
}

export interface MetricFailurePoliciesResponse {
  previews: MetricFailurePolicyMetricPreview[]
  policies: Record<string, MetricFailurePolicy>
  source: 'inferred' | 'user'
  updated_at?: string | null
}

export interface MetricClusterEligibleRow {
  evaluation_row_id: string
  conversation_id?: string | null
  row_index?: number | null
  flagged_metric_names: string[]
}

export interface MetricClusterEligibleRowsResponse {
  items: MetricClusterEligibleRow[]
  total: number
}

export interface EvaluationMetricClustersState {
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  groups: MetricClusterGroup[]
  discovered_problems: DiscoveredProblemCluster[]
  overview?: string | null
  generated_at?: string | null
  generated_at_completed_rows: number
  progress?: { completed_llm_calls: number; total_llm_calls: number } | null
  provider?: string | null
  model?: string | null
  llm_calls_used: number
  max_llm_calls?: number | null
  error_message?: string | null
  is_stale: boolean
  selected_evaluation_row_ids?: string[]
  failure_policies?: Record<string, MetricFailurePolicy>
  failure_policies_source?: 'inferred' | 'user'
  failure_policies_updated_at?: string | null
  rca_summary?: MetricClustersRcaSummary | null
}

export interface AgentFlowNode {
  id: string
  label: string
  node_type: 'start' | 'decision' | 'action' | 'terminal'
  position_x?: number | null
  position_y?: number | null
  prompt_excerpt?: string | null
  start_offset?: number | null
  end_offset?: number | null
}

export interface AgentFlowEdge {
  source: string
  target: string
  condition?: string | null
}

export interface AgentFlowGraph {
  nodes: AgentFlowNode[]
  edges: AgentFlowEdge[]
  generated_at?: string | null
  provider?: string | null
  model?: string | null
  layout_saved_at?: string | null
  prompt_content_hash?: string | null
  mapping_error?: string | null
  generation_error?: string | null
}

export interface ImportedAgent {
  id: string
  organization_id: string
  name: string
  description: string | null
  content: string
  tags: string[] | null
  current_version: number
  agent_flowchart?: AgentFlowGraph | null
  agent_flowchart_status?: string | null
  created_at: string
  updated_at: string
  created_by: string | null
}

export interface ImportedAgentDetail extends ImportedAgent {
  versions: PromptPartialVersion[]
}

export interface MetricPartialChild {
  name: string
  description: string
  example: string
}

export interface MetricPartialContent {
  schema_version: 1
  metric_kind: 'single' | 'category'
  description: string
  children?: MetricPartialChild[]
}

export interface MetricPartial {
  id: string
  organization_id: string
  name: string
  description: string | null
  content: string
  tags: string[] | null
  current_version: number
  created_at: string
  updated_at: string
  created_by: string | null
}

export interface MetricPartialDetail extends MetricPartial {
  versions: PromptPartialVersion[]
}

export interface PromptPartialVersion {
  id: string
  prompt_partial_id: string
  version: number
  content: string
  change_summary: string | null
  created_at: string
  created_by: string | null
}

export interface PromptImprovementSuggestion {
  id: string
  metric_id: string
  metric_name: string
  cluster_id: string
  cluster_label: string
  gap_label: MetricClusterGapLabel
  share_pct: number
  priority: 'high' | 'medium' | 'low'
  change_type?: 'edit' | 'add'
  target_section: string
  anchor_excerpt?: string
  current_gap: string
  suggested_text: string
  rationale: string
  flow_node_id?: string
  flow_node_label?: string
}

export interface EvaluationPromptImprovementsState {
  status: 'idle' | 'running' | 'completed' | 'failed'
  imported_agent_id?: string | null
  imported_agent_name?: string | null
  suggestions: PromptImprovementSuggestion[]
  overview?: string | null
  generated_at?: string | null
  generated_at_completed_rows: number
  provider?: string | null
  model?: string | null
  error_message?: string | null
  is_stale: boolean
}

export interface MetricPeriodDelta {
  label: string
  detail: string
  why?: string | null
}

export interface CallImportEvaluationListResponse {
  items: CallImportEvaluation[]
  total: number
}

export interface CallImportEvaluationBaselineCandidate {
  evaluation_id: string
  name: string
  dataset: string
  period_label: string | null
  period_start: string | null
  period_end: string | null
  period_display: string
  completed_rows: number
  created_at: string
  is_default: boolean
}

export interface CallImportEvaluationBaselineCandidatesResponse {
  items: CallImportEvaluationBaselineCandidate[]
  default_evaluation_id: string | null
}

export interface CallImportEvaluationRow {
  id: string
  evaluation_id: string
  call_import_row_id: string
  row_index: number | null
  /** Mandatory identifier from the source batch (renamed from ``external_call_id``). */
  conversation_id: string | null
  transcript: string | null
  raw_columns: Record<string, any> | null
  recording_url: string | null
  recording_date: string | null
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

// --- Retry (re-enqueue failed rows on an existing evaluation run) ---

export interface CallImportEvaluationRetryRequest {
  /**
   * Restrict the retry to a specific subset of evaluation rows.
   * When omitted, every row with status='failed' in this run is
   * re-enqueued.
   */
  eval_row_ids?: string[]

  /**
   * Optional LLM overrides. When provided, persisted onto the run so
   * future retries default to the new config. ``llm_provider`` and
   * ``llm_model`` must be sent together — the backend 400s on
   * half-configured input.
   */
  llm_provider?: string
  llm_model?: string
  llm_credential_id?: string | null

  /**
   * Optional STT overrides (only meaningful when the run scores the
   * diarised transcript). Same paired-field rule as LLM.
   */
  stt_provider?: string
  stt_model?: string
  stt_credential_id?: string | null

  /**
   * When true, wipe the diarised transcript on every retried row so
   * the (possibly new) STT runs from scratch. Only takes effect for
   * diarised runs that have STT config.
   */
  transcribe_overwrite?: boolean
}

export interface CallImportEvaluationRetrySkippedItem {
  eval_row_id: string
  /**
   * Why this row was not re-enqueued. Known values:
   * - 'unknown' (id not in this run)
   * - 'in_progress' (status is pending/running)
   * - 'completed' (already successful)
   * - 'source_row_missing'
   */
  reason: 'unknown' | 'in_progress' | 'completed' | 'source_row_missing'
}

export interface CallImportEvaluationRetryResponse {
  requeued: number
  /**
   * Of those, how many were chained through a diarisation task first
   * because the diarised transcript was missing.
   */
  transcribe_requeued: number
  skipped: CallImportEvaluationRetrySkippedItem[]
}

// --- Diarization / transcription ---

export interface CallImportTranscribeRequest {
  /**
   * Diarisation pipeline shape.
   * - `stt_llm` (default) — STT produces plain text, then an LLM
   *   diariser splits it into agent/user turns. STT fields required.
   * - `llm_only` — skip STT entirely and feed the audio bytes
   *   directly to a multimodal `diarization_llm_*` model along with
   *   `diarization_prompt`. STT fields MUST be omitted in this mode.
   */
  mode?: 'stt_llm' | 'llm_only'
  /** Required when `mode === 'stt_llm'`; must be null/omitted in `llm_only`. */
  stt_provider?: string | null
  /** Required when `mode === 'stt_llm'`; must be null/omitted in `llm_only`. */
  stt_model?: string | null
  credential_id?: string | null
  language?: string | null
  only_missing?: boolean
  overwrite_existing?: boolean
  row_ids?: string[]
  /**
   * LLM diariser. In `stt_llm` mode it splits the STT plain-text into
   * agent/user turns; in `llm_only` mode it directly receives the
   * audio along with `diarization_prompt`. Always required.
   */
  diarization_llm_provider: string
  diarization_llm_model: string
  diarization_llm_credential_id?: string | null
  /**
   * Operator-supplied system prompt for the diariser LLM. NULL/empty
   * means "fall back to the canonical default" (see
   * ``getDiarisationDefaultPrompt``).
   */
  diarization_prompt?: string | null
}

export interface CallImportTranscribeResponse {
  queued: number
  skipped_rows: number
  skipped_reason_counts: Record<string, number>
}

export interface CallImportRetryFailedRowsResponse {
  requeued: number
  enqueue_failed: number
  skipped: number
}

export interface CallImportDiarisationPromptDefaultResponse {
  prompt: string
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

/**
 * One unordered pair-count cell from a multi-label parent's
 * co-occurrence matrix. ``a`` and ``b`` are child label names with
 * ``a < b`` lexicographically; ``count`` is the number of rows on
 * which both labels fired together.
 */
export interface CallImportMetricLabelPair {
  a: string
  b: string
  count: number
}

export interface CallImportMetricAggregate {
  metric_id: string
  metric_name: string
  metric_type: string | null
  metric_category?: 'quality' | 'user_insight' | string
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
  /**
   * Pairwise label intersections for multi-label parent metrics.
   * Empty for everything else. The Visualizations tab reconstructs
   * a square symmetric matrix from these unordered pairs to render
   * the co-occurrence heatmap chart type.
   */
  co_occurrence?: CallImportMetricLabelPair[]
}

export interface CallImportEvaluationAggregateResponse {
  evaluation_id: string
  total_rows: number
  completed_rows: number
  failed_rows: number
  metrics: CallImportMetricAggregate[]
  period_deltas?: Record<string, MetricPeriodDelta>
  baseline_evaluation_id?: string | null
  failure_policies_source?: 'inferred' | 'user' | null
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
  metric_category?: 'quality' | 'user_insight' | string
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
   * When true, this metric is a "transcript-compare judge": at
   * call-import evaluation time the worker feeds BOTH the production
   * transcript and the diarised transcript to the LLM as a labeled
   * pair, and the run's transcript_source toggle is ignored for this
   * metric. Mutually exclusive with parent_metric_id and selection_mode
   * — comparison metrics stay standalone.
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

/**
 * One LLM-discovered candidate TOP-LEVEL metric aggregated across all
 * rows of an evaluation. Mirrors :class:`DiscoveredLabel` but adds a
 * ``suggested_type`` field — the LLM's guess at the best shape for
 * the new metric — that the promote modal can pre-fill the type radio
 * with.
 */
export interface DiscoveredMetric {
  key: string
  name: string
  description?: string | null
  suggested_type: 'boolean' | 'rating' | 'category'
  sample_rationale?: string | null
  examples?: string[]
  count: number
}

export interface DiscoveredMetricsResponse {
  evaluation_id: string
  items: DiscoveredMetric[]
}
