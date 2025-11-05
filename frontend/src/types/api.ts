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

export enum BatchStatus {
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

export interface BatchJob {
  id: string
  status: BatchStatus
  total_files: number
  processed_files: number
  failed_files: number
  evaluation_type: EvaluationType
  created_at: string
  completed_at?: string | null
}

export interface BatchCreate {
  audio_ids: string[]
  reference_texts?: Record<string, string> | null
  evaluation_type: EvaluationType
  model_name?: string | null
  metrics?: string[]
}

export interface BatchResults {
  batch_id: string
  status: BatchStatus
  total_files: number
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
  email?: string | null
}

// Integration Types
export enum IntegrationPlatform {
  RETELL = 'retell',
  VAPI = 'vapi',
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

