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

// Integration Types
export enum IntegrationPlatform {
  RETELL = 'retell',
  VAPI = 'vapi',
  CARTESIA = 'cartesia',
  ELEVENLABS = 'elevenlabs',
  DEEPGRAM = 'deepgram',
}

export interface Integration {
  id: string
  organization_id: string
  platform: IntegrationPlatform
  name?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  last_tested_at?: string | null
}

export interface IntegrationCreate {
  platform: IntegrationPlatform
  api_key: string
  name?: string | null
}

// VoiceBundle Types
export enum ModelProvider {
  OPENAI = 'openai',
  ANTHROPIC = 'anthropic',
  GOOGLE = 'google',
  AZURE = 'azure',
  AWS = 'aws',
  DEEPGRAM = 'deepgram',
  CARTESIA = 'cartesia',
  CUSTOM = 'custom',
}

// AI Provider Types
export interface AIProvider {
  id: string
  provider: ModelProvider
  api_key?: string | null
  name?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  last_tested_at?: string | null
}

export interface AIProviderCreate {
  provider: ModelProvider
  api_key: string
  name?: string | null
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
  llm_provider?: ModelProvider | null
  llm_model?: string | null
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  llm_config?: Record<string, any> | null
  tts_provider?: ModelProvider | null
  tts_model?: string | null
  tts_voice?: string | null
  tts_config?: Record<string, any> | null
  s2s_provider?: ModelProvider | null
  s2s_model?: string | null
  s2s_config?: Record<string, any> | null
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
  llm_provider?: ModelProvider | null
  llm_model?: string | null
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  llm_config?: Record<string, any> | null
  tts_provider?: ModelProvider | null
  tts_model?: string | null
  tts_voice?: string | null
  tts_config?: Record<string, any> | null
  s2s_provider?: ModelProvider | null
  s2s_model?: string | null
  s2s_config?: Record<string, any> | null
  extra_metadata?: Record<string, any> | null
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
  llm_provider?: ModelProvider
  llm_model?: string
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  llm_config?: Record<string, any> | null
  tts_provider?: ModelProvider
  tts_model?: string
  tts_voice?: string | null
  tts_config?: Record<string, any> | null
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

export interface S3ListFilesResponse {
  files: S3FileInfo[]
  total: number
  prefix?: string | null
}

export interface S3Status {
  enabled: boolean
  error?: string | null
}

