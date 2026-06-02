import axios, { AxiosInstance } from 'axios'
import type {
  AudioFile,
  Evaluation,
  EvaluationCreate,
  EvaluationResult,
  APIKey,
  MessageResponse,
  EvaluationStatus,
  OrganizationMember,
  Invitation,
  InvitationCreate,
  Profile,
  UserUpdate,
  UserPreferences,
  UserPreferencesUpdate,
  Role,
  Integration,
  IntegrationCreate,
  S3ConnectionTestResponse,
  S3ListFilesResponse,
  S3BrowseResponse,
  S3Status,
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
  CallImportEvaluationLLMOverride,
  CallImportEvaluationListResponse,
  CallImportEvaluationRow,
  CallImportEvaluationRowListResponse,
  CallImportEvaluationRetryResponse,
  CallImportEvaluationAggregateResponse,
  CallImportInsightsResponse,
  CallImportTranscribeRequest,
  CallImportTranscribeResponse,
  CallImportRetryFailedRowsResponse,
  Workspace,
} from '../types/api'

export interface EnterpriseFeatureMeta {
  title: string
  description?: string
  category?: string
}

export type EnterpriseFeatureCatalog = Record<string, EnterpriseFeatureMeta>

export type VoicePlaygroundSourceType = 'tts' | 'recording' | 'upload'

export interface VoicePlaygroundSideConfig {
  source_type: VoicePlaygroundSourceType
  provider?: string
  model?: string
  voices?: Array<{ id: string; name: string; sample_rate_hz?: number }>
  call_import_row_ids?: string[]
  upload_s3_keys?: string[]
}

export type VoicePlaygroundBlindTestRefType = 'recording' | 'upload' | 'tts_sample'

export interface VoicePlaygroundBlindTestAudioRef {
  type: VoicePlaygroundBlindTestRefType
  call_import_row_id?: string
  upload_s3_key?: string
  tts_sample_id?: string
  label?: string
}

export interface VoicePlaygroundBlindTestPair {
  text?: string
  x: VoicePlaygroundBlindTestAudioRef
  y: VoicePlaygroundBlindTestAudioRef
}

export interface LicenseInfoResponse {
  is_enterprise: boolean
  enabled_features: string[]
  all_enterprise_features: string[]
  feature_catalog?: EnterpriseFeatureCatalog
  organization?: string
}

export interface ReportBranding {
  heading?: string | null
  has_logo: boolean
  images: Array<{
    id: string
    filename: string
    content_type: string
    size_bytes: number
    role: 'internal' | 'external' | 'generic'
    updated_at?: string | null
    data_uri?: string | null
  }>
}

export interface AuthProviderConfig {
  name: 'api_key' | 'local_password' | 'external_oidc'
  enabled: boolean
  display_name: string
  description?: string
  supports_password?: boolean
  supports_signup?: boolean
  oidc_issuer?: string | null
  oidc_client_id?: string | null
  oidc_authorize_url?: string | null
}

export interface AuthConfigResponse {
  providers: AuthProviderConfig[]
  tier: 'oss' | 'enterprise'
}

export interface AuthUserSummary {
  id: string
  email: string
  name?: string | null
  first_name?: string | null
  last_name?: string | null
  organization_id: string
  role?: string | null
  has_password?: boolean
  email_is_placeholder?: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUserSummary
}

export interface TelephonyIntegrationResponse {
  id: string
  organization_id: string
  provider: string
  name?: string | null
  verify_app_uuid?: string | null
  voice_app_id?: string | null
  sip_domain?: string | null
  masking_config?: Record<string, any> | null
  is_active: boolean
  /** True if this row is the default credential for (org, provider). */
  is_default?: boolean
  last_tested_at?: string | null
  created_at: string
  updated_at: string
}

export interface TelephonyIntegrationCreatePayload {
  provider?: string
  name?: string
  auth_id: string
  auth_token: string
  verify_app_uuid?: string
  voice_app_id?: string
  sip_domain?: string
  masking_config?: Record<string, any>
  /** Mark the new credential as the default for (org, provider). */
  is_default?: boolean
}

export interface TelephonyIntegrationUpdatePayload {
  /** When set, update this specific credential row instead of the legacy single-row flow. */
  id?: string
  provider?: string
  name?: string
  auth_id?: string
  auth_token?: string
  verify_app_uuid?: string
  voice_app_id?: string
  sip_domain?: string
  masking_config?: Record<string, any>
  is_active?: boolean
}

export interface TelephonyPhoneNumberResponse {
  id: string
  phone_number: string
  country_iso2?: string | null
  region?: string | null
  number_type?: string | null
  capabilities?: Record<string, any> | null
  is_masking_pool: boolean
  agent_id?: string | null
  is_active: boolean
  created_at: string
}

type TTSReportOptionsPayload = {
  show_runs?: boolean
  min_runs_to_show?: number
  include_latency?: boolean
  include_ttfb?: boolean
  include_endpoint?: boolean
  include_naturalness?: boolean
  include_hallucination?: boolean
  include_prosody?: boolean
  include_arousal?: boolean
  include_valence?: boolean
  include_cer?: boolean
  include_wer?: boolean
  include_hallucination_examples?: boolean
  hallucination_examples_limit?: number
  include_disclaimer_sections?: boolean
  include_methodology_sections?: boolean
  zone_threshold_overrides?: Record<string, {
    good_min?: number
    neutral_min?: number
    good_max?: number
    neutral_max?: number
  }>
}

// When running in production (served from same origin), use relative path
// Otherwise use environment variable or default
const API_BASE_URL = import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD ? '' : 'http://localhost:8000')

class ApiClient {
  private client: AxiosInstance

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // Add request interceptor to add API key + active workspace to headers.
    // Workspace selection is read directly from localStorage to avoid a
    // circular import between this module and the workspace store.
    this.client.interceptors.request.use((config) => {
      const accessToken = localStorage.getItem('accessToken')
      const apiKey = localStorage.getItem('apiKey')
      const workspaceId = localStorage.getItem('activeWorkspaceId')
      if (accessToken) {
        config.headers.Authorization = `Bearer ${accessToken}`
      } else if (config.headers.Authorization) {
        delete config.headers.Authorization
      }
      if (apiKey) {
        config.headers['X-API-Key'] = apiKey
      } else if (config.headers['X-API-Key']) {
        delete config.headers['X-API-Key']
      }
      // Send X-Workspace-Id so the backend's get_workspace_id dep scopes
      // listings to the active workspace. When absent (e.g. a brand-new
      // session that hasn't called listWorkspaces yet) the backend
      // falls back to the org's Default workspace.
      if (workspaceId) {
        config.headers['X-Workspace-Id'] = workspaceId
      } else if (config.headers['X-Workspace-Id']) {
        delete config.headers['X-Workspace-Id']
      }
      return config
    })

    // Add response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        // Only log out on 401 (authentication failure)
        // 403 errors are authorization failures that should be handled by the calling code
        if (error.response?.status === 401) {
          // API key invalid, clear it
          localStorage.removeItem('apiKey')
          window.location.href = '/login'
        }
        return Promise.reject(error)
      }
    )
  }

  setApiKey(apiKey: string) {
    localStorage.setItem('apiKey', apiKey)
  }

  clearApiKey() {
    localStorage.removeItem('apiKey')
  }

  setAccessToken(accessToken: string) {
    localStorage.setItem('accessToken', accessToken)
  }

  clearAccessToken() {
    localStorage.removeItem('accessToken')
  }

  // Workspace endpoints (in-org isolation boundary for call imports + metrics).
  async listWorkspaces(): Promise<Workspace[]> {
    const response = await this.client.get('/api/v1/workspaces')
    return response.data
  }

  async createWorkspace(payload: {
    name: string
    slug?: string
  }): Promise<Workspace> {
    const response = await this.client.post('/api/v1/workspaces', payload)
    return response.data
  }

  async updateWorkspace(
    workspaceId: string,
    payload: { name: string },
  ): Promise<Workspace> {
    const response = await this.client.patch(
      `/api/v1/workspaces/${workspaceId}`,
      payload,
    )
    return response.data
  }

  async deleteWorkspace(workspaceId: string): Promise<void> {
    await this.client.delete(`/api/v1/workspaces/${workspaceId}`)
  }

  // Auth endpoints
  async getAuthConfig(): Promise<AuthConfigResponse> {
    const response = await this.client.get('/api/v1/auth/config')
    return response.data
  }

  async signup(data: {
    email: string
    password: string
    organization_name?: string
    first_name?: string
    last_name?: string
  }): Promise<TokenResponse> {
    const response = await this.client.post('/api/v1/auth/signup', data)
    return response.data
  }

  async loginWithPassword(email: string, password: string): Promise<TokenResponse> {
    const response = await this.client.post('/api/v1/auth/login', { email, password })
    return response.data
  }

  async logout(): Promise<{ success: boolean; auth_method: string }> {
    const response = await this.client.post('/api/v1/auth/logout')
    return response.data
  }

  async getMe(): Promise<AuthUserSummary> {
    const response = await this.client.get('/api/v1/auth/me')
    return response.data
  }

  async switchOrganization(organizationId: string): Promise<TokenResponse> {
    const response = await this.client.post('/api/v1/auth/switch-org', {
      organization_id: organizationId,
    })
    return response.data
  }

  async setPassword(data: {
    new_password: string
    current_password?: string
    email?: string
  }): Promise<AuthUserSummary> {
    const response = await this.client.post('/api/v1/auth/password', data)
    return response.data
  }

  async generateApiKey(name?: string): Promise<APIKey> {
    const response = await this.client.post('/api/v1/auth/generate-key', { name })
    return response.data
  }

  async validateApiKey(): Promise<{ valid: boolean; message: string }> {
    const response = await this.client.post('/api/v1/auth/validate')
    return response.data
  }

  // Settings / API Key Management endpoints
  async listApiKeys(): Promise<any[]> {
    const response = await this.client.get('/api/v1/settings/api-keys')
    return response.data
  }

  async createApiKey(name?: string): Promise<any> {
    const response = await this.client.post('/api/v1/settings/api-keys', { name })
    return response.data
  }

  async deleteApiKey(keyId: string): Promise<void> {
    await this.client.delete(`/api/v1/settings/api-keys/${keyId}`)
  }

  async regenerateApiKey(keyId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/settings/api-keys/${keyId}/regenerate`)
    return response.data
  }

  // Audio endpoints
  async uploadAudio(file: File): Promise<AudioFile> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await this.client.post('/api/v1/audio/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  }

  async getAudio(audioId: string): Promise<AudioFile> {
    const response = await this.client.get(`/api/v1/audio/${audioId}`)
    return response.data
  }

  async listAudio(skip = 0, limit = 100): Promise<AudioFile[]> {
    const response = await this.client.get('/api/v1/audio', {
      params: { skip, limit },
    })
    return response.data
  }

  async deleteAudio(audioId: string): Promise<MessageResponse> {
    const response = await this.client.delete(`/api/v1/audio/${audioId}`)
    return response.data
  }

  async downloadAudio(audioId: string): Promise<Blob> {
    const response = await this.client.get(`/api/v1/audio/${audioId}/download`, {
      responseType: 'blob',
    })
    return response.data
  }

  // Evaluation endpoints
  async createEvaluation(data: EvaluationCreate): Promise<Evaluation> {
    const response = await this.client.post('/api/v1/evaluations/create', data)
    return response.data
  }

  async getEvaluation(evaluationId: string): Promise<Evaluation> {
    const response = await this.client.get(`/api/v1/evaluations/${evaluationId}`)
    return response.data
  }

  async listEvaluations(
    skip = 0,
    limit = 100,
    status?: EvaluationStatus
  ): Promise<Evaluation[]> {
    const response = await this.client.get('/api/v1/evaluations', {
      params: { skip, limit, status },
    })
    return response.data
  }

  async cancelEvaluation(evaluationId: string): Promise<MessageResponse> {
    const response = await this.client.post(`/api/v1/evaluations/${evaluationId}/cancel`)
    return response.data
  }

  async deleteEvaluation(evaluationId: string): Promise<MessageResponse> {
    const response = await this.client.delete(`/api/v1/evaluations/${evaluationId}`)
    return response.data
  }

  // Results endpoints
  async getEvaluationResult(evaluationId: string): Promise<EvaluationResult> {
    const response = await this.client.get(`/api/v1/results/${evaluationId}`)
    return response.data
  }

  async getMetrics(evaluationId: string): Promise<{
    evaluation_id: string
    metrics: Record<string, any>
    processing_time?: number | null
  }> {
    const response = await this.client.get(`/api/v1/results/${evaluationId}/metrics`)
    return response.data
  }

  async getTranscript(evaluationId: string): Promise<{
    evaluation_id: string
    transcript: string
  }> {
    const response = await this.client.get(`/api/v1/results/${evaluationId}/transcript`)
    return response.data
  }

  async compareEvaluations(evaluationIds: string[]): Promise<{
    evaluations: EvaluationResult[]
    comparison_metrics: Record<string, any>
  }> {
    const response = await this.client.post('/api/v1/results/compare', {
      evaluation_ids: evaluationIds,
    })
    return response.data
  }

  // Agents endpoints
  async createAgent(data: {
    name: string
    phone_number?: string
    telephony_phone_number_id?: string
    language: string
    description?: string | null
    call_type: string
    call_medium: string
    voice_bundle_id?: string
    ai_provider_id?: string
    voice_ai_integration_id?: string
    voice_ai_agent_id?: string
  }): Promise<any> {
    const response = await this.client.post('/api/v1/agents', data)
    return response.data
  }

  async listAgents(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/agents', {
      params: { skip, limit },
    })
    return response.data
  }

  async getAgent(agentId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/agents/${agentId}`)
    return response.data
  }

  async updateAgent(agentId: string, data: {
    name?: string
    phone_number?: string
    telephony_phone_number_id?: string | null
    language?: string
    description?: string | null
    call_type?: string
    call_medium?: string
    voice_bundle_id?: string
    ai_provider_id?: string
    voice_ai_integration_id?: string
    voice_ai_agent_id?: string
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/agents/${agentId}`, data)
    return response.data
  }

  async deleteAgent(agentId: string, force?: boolean): Promise<any> {
    const response = await this.client.delete(`/api/v1/agents/${agentId}`, {
      params: force ? { force: true } : undefined,
    })
    return response.data
  }

  async getAgentDeleteImpact(agentId: string): Promise<{
    agent_id: string
    agent_name: string
    dependencies: Record<string, number>
    can_delete_without_force: boolean
  }> {
    const response = await this.client.get(`/api/v1/agents/${agentId}/delete-impact`)
    return response.data
  }

  async generateAgentDescription(data: {
    description: string
    tone?: string
    format_style?: string
    provider?: string
    model?: string
  }): Promise<{ content: string; provider: string; model: string }> {
    const response = await this.client.post('/api/v1/agents/generate-description', data)
    return response.data
  }

  // Personas endpoints
  async listPersonas(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/personas', {
      params: { skip, limit },
    })
    return response.data
  }

  async getPersona(personaId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/personas/${personaId}`)
    return response.data
  }

  async createPersona(data: {
    name: string
    gender: string
    tts_provider?: string
    tts_voice_id?: string
    tts_voice_name?: string
    is_custom?: boolean
  }): Promise<any> {
    const response = await this.client.post('/api/v1/personas', data)
    return response.data
  }

  async updatePersona(personaId: string, data: any): Promise<any> {
    const response = await this.client.put(`/api/v1/personas/${personaId}`, data)
    return response.data
  }

  async deletePersona(personaId: string, force?: boolean): Promise<any> {
    const response = await this.client.delete(`/api/v1/personas/${personaId}`, {
      params: force ? { force: true } : undefined,
    })
    return response.data
  }

  async clonePersona(personaId: string, name?: string): Promise<any> {
    const response = await this.client.post(`/api/v1/personas/${personaId}/clone`, { name })
    return response.data
  }

  async seedDemoData(): Promise<any> {
    const response = await this.client.post('/api/v1/personas/seed-data')
    return response.data
  }

  // Persona voice options (built-in + custom voices, ungated)
  async getPersonaVoiceOptions(provider?: string): Promise<{
    providers: Array<{
      id: string
      name: string
      voices: Array<{
        id: string
        name: string
        gender: string
        is_custom: boolean
        custom_voice_id?: string
        description?: string | null
      }>
    }>
  }> {
    const response = await this.client.get('/api/v1/personas/voice-options', {
      params: provider ? { provider } : undefined,
    })
    return response.data
  }

  // Custom voice CRUD (persona-scoped, ungated)
  async listPersonaCustomVoices(provider?: string): Promise<any[]> {
    const response = await this.client.get('/api/v1/personas/custom-voices', {
      params: provider ? { provider } : undefined,
    })
    return response.data
  }

  async createPersonaCustomVoice(data: {
    provider: string
    voice_id: string
    name: string
    gender?: string
    description?: string
  }): Promise<any> {
    const response = await this.client.post('/api/v1/personas/custom-voices', data)
    return response.data
  }

  async updatePersonaCustomVoice(customVoiceId: string, data: {
    voice_id?: string
    name?: string
    gender?: string
    description?: string
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/personas/custom-voices/${customVoiceId}`, data)
    return response.data
  }

  async deletePersonaCustomVoice(customVoiceId: string): Promise<any> {
    const response = await this.client.delete(`/api/v1/personas/custom-voices/${customVoiceId}`)
    return response.data
  }

  // Scenarios endpoints
  async listScenarios(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/scenarios', {
      params: { skip, limit },
    })
    return response.data
  }

  async getScenario(scenarioId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/scenarios/${scenarioId}`)
    return response.data
  }

  async createScenario(data: {
    name: string
    agent_id?: string | null
    description?: string | null
    required_info: Record<string, string>
  }): Promise<any> {
    const response = await this.client.post('/api/v1/scenarios', data)
    return response.data
  }

  async updateScenario(scenarioId: string, data: {
    name?: string
    agent_id?: string | null
    description?: string | null
    required_info?: Record<string, string>
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/scenarios/${scenarioId}`, data)
    return response.data
  }

  async deleteScenario(scenarioId: string, force?: boolean): Promise<any> {
    const response = await this.client.delete(`/api/v1/scenarios/${scenarioId}`, {
      params: force ? { force: true } : undefined,
    })
    return response.data
  }

  // Chat/Inference endpoints
  async chatCompletion(data: {
    messages: Array<{ role: string; content: string }>
    provider: string
    model: string
    temperature?: number
    max_tokens?: number
  }): Promise<{
    text: string
    model: string
    usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
    processing_time?: number
  }> {
    const response = await this.client.post('/api/v1/chat/completion', data)
    return response.data
  }

  // VoiceBundle endpoints
  async listVoiceBundles(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/voicebundles', {
      params: { skip, limit },
    })
    return response.data
  }

  async getVoiceBundle(voicebundleId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/voicebundles/${voicebundleId}`)
    return response.data
  }

  async createVoiceBundle(data: any): Promise<any> {
    const response = await this.client.post('/api/v1/voicebundles', data)
    return response.data
  }

  async updateVoiceBundle(voicebundleId: string, data: any): Promise<any> {
    const response = await this.client.put(`/api/v1/voicebundles/${voicebundleId}`, data)
    return response.data
  }

  async deleteVoiceBundle(voicebundleId: string, force?: boolean): Promise<any> {
    const response = await this.client.delete(`/api/v1/voicebundles/${voicebundleId}`, {
      params: force ? { force: true } : undefined,
    })
    return response.data
  }

  // AI Provider endpoints
  async listAIProviders(): Promise<any[]> {
    const response = await this.client.get('/api/v1/aiproviders')
    return response.data
  }

  async getAIProvider(aiproviderId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/aiproviders/${aiproviderId}`)
    return response.data
  }

  async createAIProvider(data: any): Promise<any> {
    const response = await this.client.post('/api/v1/aiproviders', data)
    return response.data
  }

  async updateAIProvider(aiproviderId: string, data: any): Promise<any> {
    const response = await this.client.put(`/api/v1/aiproviders/${aiproviderId}`, data)
    return response.data
  }

  async deleteAIProvider(aiproviderId: string): Promise<void> {
    await this.client.delete(`/api/v1/aiproviders/${aiproviderId}`)
  }

  async setDefaultAIProvider(aiproviderId: string): Promise<any> {
    const response = await this.client.post(
      `/api/v1/aiproviders/${aiproviderId}/set-default`,
    )
    return response.data
  }

  async testAIProvider(aiproviderId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/aiproviders/${aiproviderId}/test`)
    return response.data
  }

  // IAM endpoints
  async listOrganizationUsers(): Promise<OrganizationMember[]> {
    const response = await this.client.get('/api/v1/iam/users')
    return response.data
  }

  async inviteUser(data: InvitationCreate): Promise<Invitation> {
    const response = await this.client.post('/api/v1/iam/invitations', data)
    return response.data
  }

  async listInvitations(): Promise<Invitation[]> {
    const response = await this.client.get('/api/v1/iam/invitations')
    return response.data
  }

  async updateUserRole(userId: string, role: Role): Promise<OrganizationMember> {
    const response = await this.client.put(`/api/v1/iam/users/${userId}/role`, { role })
    return response.data
  }

  async removeUser(userId: string): Promise<void> {
    await this.client.delete(`/api/v1/iam/users/${userId}`)
  }

  async cancelInvitation(invitationId: string): Promise<void> {
    await this.client.delete(`/api/v1/iam/invitations/${invitationId}`)
  }

  /**
   * Admin-initiated password reset for another organization member.
   *
   * The caller must be an ADMIN of the same organization as `userId`. The
   * backend ignores any current-password concept here (that's for the
   * self-service `/auth/password` endpoint). Communicate the new password
   * to the user out-of-band.
   */
  async adminResetUserPassword(
    userId: string,
    newPassword: string,
  ): Promise<{ user_id: string; email: string; message: string }> {
    const response = await this.client.post(
      `/api/v1/iam/users/${userId}/reset-password`,
      { new_password: newPassword },
    )
    return response.data
  }

  // Profile endpoints
  async getProfile(): Promise<Profile> {
    const response = await this.client.get('/api/v1/profile')
    return response.data
  }

  async updateProfile(data: UserUpdate): Promise<Profile> {
    const response = await this.client.put('/api/v1/profile', data)
    return response.data
  }

  async getMyInvitations(): Promise<Invitation[]> {
    const response = await this.client.get('/api/v1/profile/invitations')
    return response.data
  }

  async acceptInvitation(invitationId: string): Promise<MessageResponse> {
    const response = await this.client.post(`/api/v1/profile/invitations/${invitationId}/accept`)
    return response.data
  }

  async declineInvitation(invitationId: string): Promise<MessageResponse> {
    const response = await this.client.post(`/api/v1/profile/invitations/${invitationId}/decline`)
    return response.data
  }

  // User Preferences endpoints
  async getUserPreferences(): Promise<UserPreferences> {
    const response = await this.client.get('/api/v1/profile/preferences')
    return response.data
  }

  async updateUserPreferences(data: UserPreferencesUpdate): Promise<UserPreferences> {
    const response = await this.client.put('/api/v1/profile/preferences', data)
    return response.data
  }

  // Integration endpoints
  async listIntegrations(): Promise<Integration[]> {
    const response = await this.client.get('/api/v1/integrations')
    return response.data
  }

  async getIntegration(integrationId: string): Promise<Integration> {
    const response = await this.client.get(`/api/v1/integrations/${integrationId}`)
    return response.data
  }

  async createIntegration(data: IntegrationCreate): Promise<Integration> {
    const response = await this.client.post('/api/v1/integrations', data)
    return response.data
  }

  async updateIntegration(integrationId: string, data: Partial<IntegrationCreate>): Promise<Integration> {
    const response = await this.client.put(`/api/v1/integrations/${integrationId}`, data)
    return response.data
  }

  async deleteIntegration(integrationId: string, force?: boolean): Promise<any> {
    const response = await this.client.delete(`/api/v1/integrations/${integrationId}`, {
      params: force ? { force: true } : undefined,
    })
    return response.data
  }

  async setDefaultIntegration(integrationId: string): Promise<Integration> {
    const response = await this.client.post(
      `/api/v1/integrations/${integrationId}/set-default`,
    )
    return response.data
  }

  async getIntegrationApiKey(integrationId: string): Promise<{ api_key: string; public_key?: string | null }> {
    const response = await this.client.get(`/api/v1/integrations/${integrationId}/api-key`)
    return response.data
  }

  // Telephony endpoints (provider-agnostic)
  async createTelephonyConfig(data: TelephonyIntegrationCreatePayload): Promise<TelephonyIntegrationResponse> {
    const response = await this.client.post('/api/v1/telephony/config', data)
    return response.data
  }

  async getTelephonyConfig(provider: string = 'plivo'): Promise<TelephonyIntegrationResponse> {
    const response = await this.client.get('/api/v1/telephony/config', { params: { provider } })
    return response.data
  }

  async listTelephonyConfigs(provider?: string): Promise<TelephonyIntegrationResponse[]> {
    const response = await this.client.get('/api/v1/telephony/configs', {
      params: provider ? { provider } : undefined,
    })
    return response.data
  }

  async updateTelephonyConfig(data: TelephonyIntegrationUpdatePayload): Promise<TelephonyIntegrationResponse> {
    const response = await this.client.put('/api/v1/telephony/config', data)
    return response.data
  }

  async setDefaultTelephonyConfig(integrationId: string): Promise<TelephonyIntegrationResponse> {
    const response = await this.client.post(
      `/api/v1/telephony/config/${integrationId}/set-default`,
    )
    return response.data
  }

  async deleteTelephonyConfig(integrationId: string): Promise<void> {
    await this.client.delete(`/api/v1/telephony/config/${integrationId}`)
  }

  async listTelephonyNumbers(provider?: string): Promise<TelephonyPhoneNumberResponse[]> {
    const response = await this.client.get('/api/v1/telephony/numbers', {
      params: provider ? { provider } : undefined,
    })
    return response.data
  }

  // Data Sources endpoints
  async testS3Connection(): Promise<S3ConnectionTestResponse> {
    const response = await this.client.post('/api/v1/data-sources/s3/test')
    return response.data
  }

  async listS3Files(prefix?: string, maxKeys = 1000): Promise<S3ListFilesResponse> {
    const response = await this.client.get('/api/v1/data-sources/s3/files', {
      params: { prefix, max_keys: maxKeys },
    })
    return response.data
  }

  async browseS3(path = '', maxKeys = 1000): Promise<S3BrowseResponse> {
    const response = await this.client.get('/api/v1/data-sources/s3/browse', {
      params: { path, max_keys: maxKeys },
    })
    return response.data
  }

  async uploadToS3(file: File, customFilename?: string): Promise<MessageResponse> {
    const formData = new FormData()
    formData.append('file', file)
    if (customFilename) {
      formData.append('filename', customFilename)
    }
    const response = await this.client.post('/api/v1/data-sources/s3/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  }

  async getS3Status(): Promise<S3Status> {
    const response = await this.client.get('/api/v1/data-sources/s3/status')
    return response.data
  }

  async downloadFromS3(fileKey: string): Promise<void> {
    const response = await this.client.get(`/api/v1/data-sources/s3/files/${encodeURIComponent(fileKey)}/download`, {
      responseType: 'blob',
    })
    // Create a blob URL and trigger download
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', fileKey.split('/').pop() || 'file')
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  async getS3PresignedUrl(fileKey: string, expiration: number = 3600): Promise<{ url: string; expires_in: number }> {
    const response = await this.client.get(`/api/v1/data-sources/s3/files/${encodeURIComponent(fileKey)}/presigned-url`, {
      params: { expiration },
    })
    return response.data
  }

  async deleteFromS3(fileKey: string): Promise<MessageResponse> {
    const response = await this.client.delete(`/api/v1/data-sources/s3/files/${encodeURIComponent(fileKey)}`)
    return response.data
  }

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
    const formData = new FormData()
    formData.append('file', file)
    formData.append('provider', options.provider)
    formData.append('telephony_integration_id', options.telephonyIntegrationId)
    formData.append('schema_id', options.schemaId)
    formData.append('parameter_mapping', JSON.stringify(options.parameterMapping))
    formData.append('skipped_columns', JSON.stringify(options.skippedColumns || []))
    if (options.dataset !== undefined && options.dataset !== null) {
      formData.append('dataset', options.dataset)
    }
    if (options.tagIds && options.tagIds.length > 0) {
      for (const tagId of options.tagIds) {
        formData.append('tag_ids', tagId)
      }
    }
    if (options.sheetName) {
      formData.append('sheet_name', options.sheetName)
    }
    const response = await this.client.post('/api/v1/call-imports/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
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
      /**
       * Optional schema pre-pick. The user can still change it during
       * the MAP stage; provided here only so the detail page can pre-
       * select the schema dropdown.
       */
      schemaId?: string | null
    },
  ): Promise<CallImport> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('dataset', options.dataset)
    if (options.tagIds && options.tagIds.length > 0) {
      for (const tagId of options.tagIds) {
        formData.append('tag_ids', tagId)
      }
    }
    if (options.schemaId) {
      formData.append('schema_id', options.schemaId)
    }
    const response = await this.client.post('/api/v1/call-imports', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async uploadCallImportAudio(
    files: File[],
    options: {
      dataset: string
      tagIds?: string[]
    },
  ): Promise<CallImportUploadResponse> {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    formData.append('dataset', options.dataset)
    if (options.tagIds && options.tagIds.length > 0) {
      for (const tagId of options.tagIds) {
        formData.append('tag_ids', tagId)
      }
    }
    const response = await this.client.post('/api/v1/call-imports/audio-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
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
      provider: string
      telephonyIntegrationId: string
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

  async deleteCallImport(id: string): Promise<void> {
    await this.client.delete(`/api/v1/call-imports/${id}`)
  }

  async deleteCallImportRow(id: string, rowId: string): Promise<void> {
    await this.client.delete(`/api/v1/call-imports/${id}/rows/${rowId}`)
  }

  async bulkDeleteCallImportRows(
    id: string,
    rowIds: string[],
  ): Promise<{ deleted: number }> {
    const response = await this.client.post(
      `/api/v1/call-imports/${id}/rows/bulk-delete`,
      { row_ids: rowIds },
    )
    return response.data
  }

  async createCallImportEvaluation(
    callImportId: string,
    payload: {
      metric_ids: string[]
      name?: string | null
      /**
       * Which transcript(s) to score against. Passing both values triggers
       * two evaluation runs (one per source). Defaults server-side to
       * `['production']` for backwards compatibility.
       */
      transcript_sources?: Array<'production' | 'diarised'>
      /** Run-level LLM provider key. Leave undefined for legacy default. */
      llm_provider?: string | null
      llm_model?: string | null
      llm_credential_id?: string | null
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
  ): Promise<CallImportEvaluationAggregateResponse> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/aggregate`,
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
  ): Promise<import('../types/api').EvaluationTldrSummary | null> {
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
      max_llm_calls?: number | null
    },
  ): Promise<import('../types/api').EvaluationTldrSummary> {
    const body: Record<string, unknown> = {
      regenerate: Boolean(options?.regenerate),
    }
    if (options?.provider) body.provider = options.provider
    if (options?.model) body.model = options.model
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
  ): Promise<import('../types/api').EvaluationUserInsightsState | null> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/user-insights`,
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
      max_llm_calls?: number | null
    },
  ): Promise<import('../types/api').EvaluationUserInsightsState> {
    const body: Record<string, unknown> = {
      regenerate: Boolean(options?.regenerate),
      force: Boolean(options?.force),
    }
    if (options?.provider) body.provider = options.provider
    if (options?.model) body.model = options.model
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
  ): Promise<import('../types/api').MetricFlowResponse> {
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
  ): Promise<import('../types/api').DiscoveredLabelsResponse> {
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
  ): Promise<import('../types/api').DiscoveredLabelsResponse> {
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
  ): Promise<import('../types/api').DiscoveredLabelsResponse> {
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
  ): Promise<import('../types/api').MetricSummary> {
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
  ): Promise<import('../types/api').DiscoveredMetricsResponse> {
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
  ): Promise<import('../types/api').DiscoveredMetricsResponse> {
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
  ): Promise<import('../types/api').DiscoveredMetricsResponse> {
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
  }): Promise<import('../types/api').MetricSummary> {
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
  ): Promise<CallImportRetryFailedRowsResponse> {
    const response = await this.client.post(
      `/api/v1/call-imports/${callImportId}/retry-failed`,
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
    rowIds?: string[] | null,
  ): Promise<{ cancelled: number; skipped: number }> {
    const body =
      rowIds === undefined || rowIds === null
        ? {}
        : { row_ids: rowIds }
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
      llmProvider?: string | null
      llmModel?: string | null
      llmCredentialId?: string | null
      sttProvider?: string | null
      sttModel?: string | null
      sttCredentialId?: string | null
      transcribeOverwrite?: boolean
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
    },
  ): Promise<CallImportEvaluationRetryResponse> {
    const body: Record<string, unknown> = {}
    if (options?.evalRowIds && options.evalRowIds.length > 0) {
      body.eval_row_ids = options.evalRowIds
    }
    if (options?.llmProvider) body.llm_provider = options.llmProvider
    if (options?.llmModel) body.llm_model = options.llmModel
    if (options?.llmCredentialId !== undefined) {
      body.llm_credential_id = options.llmCredentialId
    }
    if (options?.sttProvider) body.stt_provider = options.sttProvider
    if (options?.sttModel) body.stt_model = options.sttModel
    if (options?.sttCredentialId !== undefined) {
      body.stt_credential_id = options.sttCredentialId
    }
    if (options?.transcribeOverwrite) {
      body.transcribe_overwrite = true
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
  ): Promise<CallImportEvaluation> {
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
  ): Promise<CallImportEvaluation> {
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

  async exportCallImportEvaluation(
    callImportId: string,
    evaluationId: string,
    format: 'csv' | 'xlsx' = 'csv',
  ): Promise<Blob> {
    const response = await this.client.get(
      `/api/v1/call-imports/${callImportId}/evaluations/${evaluationId}/export`,
      { params: { format }, responseType: 'blob' },
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
    },
  ): Promise<Blob> {
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
      },
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

  // Model Config endpoints
  async getAllModels(): Promise<Record<string, any>> {
    const response = await this.client.get('/api/v1/model-config/models')
    return response.data
  }

  async getModelConfig(modelName: string): Promise<any> {
    const response = await this.client.get(`/api/v1/model-config/models/${modelName}`)
    return response.data
  }

  async getModelsByProvider(provider: string): Promise<string[]> {
    const response = await this.client.get(`/api/v1/model-config/providers/${provider}/models`)
    return response.data
  }

  async getModelOptions(provider: string): Promise<{ stt: string[]; llm: string[]; tts: string[]; s2s: string[]; tts_voices: Record<string, { id: string; name: string; gender?: string }[]> }> {
    const response = await this.client.get(`/api/v1/model-config/providers/${provider}/options`)
    const data = response.data
    // Ensure s2s and tts_voices are always present (for backward compatibility)
    return {
      ...data,
      s2s: data.s2s || [],
      tts_voices: data.tts_voices || {},
    }
  }

  async getModelsByType(provider: string, modelType: 'stt' | 'llm' | 'tts'): Promise<string[]> {
    const response = await this.client.get(`/api/v1/model-config/providers/${provider}/types/${modelType}/models`)
    return response.data
  }

  // Manual Evaluations endpoints
  async listManualEvaluationAudioFiles(prefix?: string, maxKeys = 1000): Promise<S3ListFilesResponse> {
    const response = await this.client.get('/api/v1/manual-evaluations/audio-files', {
      params: { prefix, max_keys: maxKeys },
    })
    return response.data
  }

  async getAudioPresignedUrl(fileKey: string, expiration = 3600): Promise<{ url: string; expires_in: number }> {
    const response = await this.client.get(
      `/api/v1/manual-evaluations/audio-files/${encodeURIComponent(fileKey)}/presigned-url`,
      {
        params: { expiration },
      }
    )
    return response.data
  }

  async transcribeAudio(data: {
    audio_file_key: string
    stt_provider: string
    stt_model: string
    name?: string
    language?: string
    enable_speaker_diarization?: boolean
  }): Promise<any> {
    const response = await this.client.post('/api/v1/manual-evaluations/transcribe', data)
    return response.data
  }

  async listManualTranscriptions(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/manual-evaluations/transcriptions', {
      params: { skip, limit },
    })
    return response.data
  }

  async getManualTranscription(transcriptionId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/manual-evaluations/transcriptions/${transcriptionId}`)
    return response.data
  }

  async updateManualTranscription(transcriptionId: string, name: string): Promise<any> {
    const response = await this.client.patch(`/api/v1/manual-evaluations/transcriptions/${transcriptionId}`, { name })
    return response.data
  }

  async deleteManualTranscription(transcriptionId: string): Promise<MessageResponse> {
    const response = await this.client.delete(`/api/v1/manual-evaluations/transcriptions/${transcriptionId}`)
    return response.data
  }

  // Test Agent endpoints
  async createTestAgentConversation(data: {
    agent_id: string
    persona_id: string
    scenario_id: string
    voice_bundle_id: string
    conversation_metadata?: Record<string, any>
  }): Promise<any> {
    const response = await this.client.post('/api/v1/test-agents/conversations', data)
    return response.data
  }

  async getTestAgentConversation(conversationId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/test-agents/conversations/${conversationId}`)
    return response.data
  }

  async listTestAgentConversations(): Promise<any[]> {
    const response = await this.client.get('/api/v1/test-agents/conversations')
    return response.data
  }

  async startTestAgentConversation(conversationId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/test-agents/conversations/${conversationId}/start`)
    return response.data
  }

  async processTestAgentAudio(conversationId: string, audioFile: File, chunkTimestamp?: number): Promise<any> {
    const formData = new FormData()
    formData.append('audio_file', audioFile)
    if (chunkTimestamp !== undefined) {
      formData.append('chunk_timestamp', chunkTimestamp.toString())
    }
    const response = await this.client.post(
      `/api/v1/test-agents/conversations/${conversationId}/process-audio`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  }

  async getTestAgentResponseAudio(conversationId: string): Promise<Blob> {
    const response = await this.client.get(
      `/api/v1/test-agents/conversations/${conversationId}/response-audio`,
      {
        responseType: 'blob',
      }
    )
    return response.data
  }

  async endTestAgentConversation(conversationId: string, finalAudioKey?: string): Promise<any> {
    const response = await this.client.post(`/api/v1/test-agents/conversations/${conversationId}/end`, {
      final_audio_key: finalAudioKey,
    })
    return response.data
  }

  async deleteTestAgentConversation(conversationId: string): Promise<void> {
    await this.client.delete(`/api/v1/test-agents/conversations/${conversationId}`)
  }

  // Voice Agent endpoints
  async getVoiceAgentConnection(): Promise<{ ws_url: string; endpoint: string }> {
    const response = await this.client.post('/api/v1/voice-agent/connect')
    return response.data
  }

  // Playground endpoints
  async createWebCall(data: {
    agent_id: string
    metadata?: Record<string, any>
    retell_llm_dynamic_variables?: Record<string, any>
    custom_sip_headers?: Record<string, string>
  }): Promise<{
    call_type: string
    access_token?: string
    call_id: string
    agent_id: string
    agent_version?: number
    call_status?: string
    agent_name?: string
    metadata?: Record<string, any>
    retell_llm_dynamic_variables?: Record<string, any>
    sample_rate?: number
    call_short_id?: string
    signed_url?: string
    host?: string
    room_name?: string
    conversation_id?: string
  }> {
    const response = await this.client.post('/api/v1/playground/web-call', data)
    return response.data
  }

  async listCallRecordings(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/playground/call-recordings', {
      params: { skip, limit },
    })
    return response.data
  }

  async getCallRecording(callShortId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/playground/call-recordings/${callShortId}`)
    return response.data
  }

  async refreshCallRecording(callShortId: string): Promise<{ message: string }> {
    const response = await this.client.post(`/api/v1/playground/call-recordings/${callShortId}/refresh`)
    return response.data
  }

  async updateCallRecording(callShortId: string, providerCallId: string): Promise<{ message: string; provider_call_id: string }> {
    const response = await this.client.put(`/api/v1/playground/call-recordings/${callShortId}`, {
      provider_call_id: providerCallId
    })
    return response.data
  }

  async deleteCallRecording(callShortId: string): Promise<{ message: string }> {
    const response = await this.client.delete(`/api/v1/playground/call-recordings/${callShortId}`)
    return response.data
  }

  async reEvaluateCallRecording(callShortId: string): Promise<{
    message: string
    evaluator_result_id: string
    result_id: string
    audio_s3_key: string
    task_id: string
  }> {
    const response = await this.client.post(`/api/v1/playground/call-recordings/${callShortId}/re-evaluate`)
    return response.data
  }

  async getCallRecordingAudioUrl(callShortId: string): Promise<string> {
    const response = await this.client.get(
      `/api/v1/playground/call-recordings/${callShortId}/audio`,
      { responseType: 'blob' }
    )
    return URL.createObjectURL(response.data)
  }

  async createCustomWebsocketSession(data: {
    agent_id: string
    websocket_url: string
    transcript_entries: Array<{ role: 'user' | 'agent'; content: string; timestamp: string }>
    started_at?: string
    ended_at?: string
    audio_file?: File
  }): Promise<{
    message: string
    call_short_id: string
    audio_s3_key?: string | null
    evaluator_result_id?: string | null
  }> {
    const formData = new FormData()
    formData.append('agent_id', data.agent_id)
    formData.append('websocket_url', data.websocket_url)
    formData.append('transcript_entries', JSON.stringify(data.transcript_entries))
    if (data.started_at) {
      formData.append('started_at', data.started_at)
    }
    if (data.ended_at) {
      formData.append('ended_at', data.ended_at)
    }
    if (data.audio_file) {
      formData.append('audio_file', data.audio_file)
    }

    const response = await this.client.post('/api/v1/playground/custom-websocket-sessions', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  }

  async evaluateCustomWebsocketSession(callShortId: string): Promise<{
    message: string
    evaluator_result_id: string
    result_id: string
    task_id: string
  }> {
    const response = await this.client.post(`/api/v1/playground/custom-websocket-sessions/${callShortId}/evaluate`)
    return response.data
  }

  async getAgentSttConfig(agentId: string): Promise<{
    available: boolean
    provider?: string
    model?: string
    reason?: string
  }> {
    const response = await this.client.get(`/api/v1/playground/agents/${agentId}/stt-config`)
    return response.data
  }

  async transcribeTurn(
    agentId: string,
    channel: 'user' | 'agent',
    audioBlob: Blob,
  ): Promise<{ transcript: string; channel: string }> {
    const formData = new FormData()
    formData.append('agent_id', agentId)
    formData.append('channel', channel)
    formData.append('audio_file', audioBlob, `turn_${channel}_${Date.now()}.wav`)
    const response = await this.client.post('/api/v1/playground/transcribe-turn', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async summarizeTranscript(params: {
    transcript?: string
    entries?: Array<{ role: string; content: string; timestamp?: string }>
    callShortId?: string
    agentId?: string
    force?: boolean
  }): Promise<{
    summary: string
    provider: string
    model: string
    source?: 'voice_bundle' | 'org_fallback'
    cached?: boolean
    generated_at?: string
    usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
  }> {
    const body: Record<string, any> = {}
    if (params.transcript) body.transcript = params.transcript
    if (params.entries && params.entries.length > 0) body.entries = params.entries
    if (params.callShortId) body.call_short_id = params.callShortId
    if (params.agentId) body.agent_id = params.agentId
    if (params.force) body.force = true
    const response = await this.client.post('/api/v1/playground/summarize-transcript', body)
    return response.data
  }

  // Observability endpoints
  async listObservabilityCalls(skip = 0, limit = 100): Promise<any[]> {
    const response = await this.client.get('/api/v1/observability/calls', {
      params: { skip, limit },
    })
    return response.data
  }

  async getObservabilityCall(callShortId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/observability/calls/${callShortId}`)
    return response.data
  }

  async deleteObservabilityCall(callShortId: string): Promise<{ message: string }> {
    const response = await this.client.delete(`/api/v1/observability/calls/${callShortId}`)
    return response.data
  }

  async evaluateObservabilityCall(callShortId: string, evaluatorId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/observability/calls/${callShortId}/evaluate`, {
      evaluator_id: evaluatorId,
    })
    return response.data
  }

  // Evaluator endpoints
  async createEvaluator(data: {
    name?: string
    agent_id?: string
    persona_id?: string
    scenario_id?: string
    custom_prompt?: string
    metric_ids?: string[]
    llm_provider?: string
    llm_model?: string
    tags?: string[]
  }): Promise<any> {
    const response = await this.client.post('/api/v1/evaluators', data)
    return response.data
  }

  async formatCustomPrompt(prompt: string): Promise<{ formatted_prompt: string }> {
    const response = await this.client.post('/api/v1/evaluators/format-prompt', { prompt })
    return response.data
  }

  async createEvaluatorsBulk(data: {
    name?: string
    agent_id: string
    scenario_id: string
    persona_ids: string[]
    tags?: string[]
  }): Promise<any[]> {
    const response = await this.client.post('/api/v1/evaluators/bulk', data)
    return response.data
  }

  async listEvaluators(): Promise<any[]> {
    const response = await this.client.get('/api/v1/evaluators')
    return response.data
  }

  async getEvaluator(evaluatorId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/evaluators/${evaluatorId}`)
    return response.data
  }

  async updateEvaluator(evaluatorId: string, data: {
    agent_id?: string
    persona_id?: string
    scenario_id?: string
    name?: string
    custom_prompt?: string
    metric_ids?: string[]
    llm_provider?: string
    llm_model?: string
    tags?: string[]
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/evaluators/${evaluatorId}`, data)
    return response.data
  }

  async deleteEvaluator(evaluatorId: string, force?: boolean): Promise<any> {
    const response = await this.client.delete(`/api/v1/evaluators/${evaluatorId}`, {
      params: force ? { force: true } : undefined,
    })
    return response.data
  }

  async runEvaluators(evaluatorIds: string[]): Promise<{ task_ids: string[]; evaluator_results: any[] }> {
    const response = await this.client.post('/api/v1/evaluators/run', { evaluator_ids: evaluatorIds })
    return response.data
  }

  // Metric endpoints
  async createMetric(data: {
    name: string
    description?: string
    /**
     * Optional illustrative example surfaced alongside the description
     * in the LLM judge's rubric. Mainly used by categorization label
     * children but accepted on every metric.
     */
    example?: string | null
    metric_type: 'number' | 'boolean' | 'rating' | 'text'
    trigger?: 'always'
    enabled?: boolean
    metric_origin?: 'default' | 'custom'
    supported_surfaces?: string[]
    enabled_surfaces?: string[]
    custom_data_type?: 'boolean' | 'enum' | 'number_range'
    custom_config?: Record<string, any>
    tags?: string[]
    capture_rationale?: boolean
    parent_metric_id?: string | null
    selection_mode?: 'single_choice' | 'multi_label' | null
    /**
     * Scope of the new metric:
     *   - "workspace" (default): stamped with the active X-Workspace-Id
     *     header so it only appears inside that workspace.
     *   - "organization": stored with workspace_id=NULL so it surfaces
     *     in every workspace of the caller's org.
     * Ignored when parent_metric_id is set — children always inherit
     * their parent's scope.
     */
    scope?: 'workspace' | 'organization'
  }): Promise<any> {
    const response = await this.client.post('/api/v1/metrics', data)
    return response.data
  }

  /**
   * Atomically create a parent (category) metric + N children, used by
   * the "Create category" flow on the Metrics page and by the
   * /parse-bulk → save path when a hierarchy was requested.
   */
  async createMetricWithChildren(data: {
    name: string
    description?: string | null
    selection_mode: 'single_choice' | 'multi_label'
    enabled?: boolean
    supported_surfaces?: string[]
    enabled_surfaces?: string[]
    tags?: string[] | null
    allow_discovery?: boolean
    /**
     * Parent-level "Enable LLM Rationale" toggle. When true the LLM
     * judge emits one rationale at the category level (children never
     * carry rationales in hierarchical mode).
     */
    capture_rationale?: boolean
    children: Array<{
      name: string
      description?: string | null
      /**
       * Optional illustrative example for this label, surfaced
       * alongside the description in the LLM judge's rubric.
       */
      example?: string | null
      enabled?: boolean
      capture_rationale?: boolean | null
      tags?: string[] | null
    }>
    /**
     * Same semantics as {@link createMetric}'s ``scope``: when
     * ``"organization"`` the parent + every child are stored with
     * ``workspace_id=NULL`` so the whole category subtree is visible
     * in every workspace of the org.
     */
    scope?: 'workspace' | 'organization'
  }): Promise<any> {
    const response = await this.client.post(
      '/api/v1/metrics/with-children',
      data,
    )
    return response.data
  }

  async addMetricChild(parentMetricId: string, data: {
    name: string
    description?: string | null
    /**
     * Optional illustrative example for this label, surfaced alongside
     * the description in the LLM judge's rubric.
     */
    example?: string | null
    enabled?: boolean
    capture_rationale?: boolean | null
    tags?: string[] | null
  }): Promise<any> {
    const response = await this.client.post(
      `/api/v1/metrics/${parentMetricId}/children`,
      data,
    )
    return response.data
  }

  async listMetrics(surface?: string, includeChildren: boolean = true): Promise<any[]> {
    const response = await this.client.get('/api/v1/metrics', {
      params: {
        ...(surface ? { surface } : {}),
        include_children: includeChildren,
      },
    })
    return response.data
  }

  // Evaluator Results endpoints
  async listEvaluatorResults(evaluatorId?: string, playground?: boolean, testAgentsOnly?: boolean): Promise<any[]> {
    const params: any = {}
    if (evaluatorId) {
      params.evaluator_id = evaluatorId
    }
    if (playground !== undefined) {
      params.playground = playground
    }
    if (testAgentsOnly !== undefined) {
      params.test_agents_only = testAgentsOnly
    }
    const response = await this.client.get('/api/v1/evaluator-results', { params })
    return response.data
  }

  async getEvaluatorResult(id: string, includeRelations: boolean = true): Promise<any> {
    const params = includeRelations ? { include_relations: 'true' } : {}
    const response = await this.client.get(`/api/v1/evaluator-results/${id}`, { params })
    return response.data
  }

  async getEvaluatorResultMetrics(id: string): Promise<any> {
    const response = await this.client.get(`/api/v1/evaluator-results/${id}/metrics`)
    return response.data
  }

  async createEvaluatorResultManual(data: {
    evaluator_id: string
    audio_s3_key: string
    duration_seconds?: number
  }): Promise<any> {
    const response = await this.client.post('/api/v1/evaluator-results', data)
    return response.data
  }

  async reEvaluateResult(id: string): Promise<any> {
    const response = await this.client.post(`/api/v1/evaluator-results/${id}/re-evaluate`)
    return response.data
  }

  async deleteEvaluatorResult(id: string): Promise<void> {
    await this.client.delete(`/api/v1/evaluator-results/${id}`)
  }

  async deleteEvaluatorResultsBulk(ids: string[]): Promise<void> {
    // FastAPI expects multiple query parameters with the same name
    // Build query string manually: result_ids=id1&result_ids=id2
    const params = new URLSearchParams()
    ids.forEach(id => params.append('result_ids', id))
    await this.client.delete(`/api/v1/evaluator-results?${params.toString()}`)
  }

  async getMetric(metricId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/metrics/${metricId}`)
    return response.data
  }

  async updateMetric(metricId: string, data: {
    name?: string
    description?: string
    /**
     * Pass ``""`` (empty string) to clear the stored example; omit to
     * leave the persisted value untouched.
     */
    example?: string | null
    metric_type?: 'number' | 'boolean' | 'rating' | 'text'
    trigger?: 'always'
    enabled?: boolean
    metric_origin?: 'default' | 'custom'
    supported_surfaces?: string[]
    enabled_surfaces?: string[]
    custom_data_type?: 'boolean' | 'enum' | 'number_range'
    custom_config?: Record<string, any>
    tags?: string[]
    capture_rationale?: boolean
    selection_mode?: 'single_choice' | 'multi_label' | null
    /** Only honored on multi_label parents; backend 400s otherwise. */
    allow_discovery?: boolean
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/metrics/${metricId}`, data)
    return response.data
  }

  async deleteMetric(metricId: string): Promise<void> {
    await this.client.delete(`/api/v1/metrics/${metricId}`)
  }

  async seedDefaultMetrics(): Promise<any[]> {
    const response = await this.client.post('/api/v1/metrics/seed-defaults')
    return response.data
  }

  async generateMetric(data: {
    mode: 'description' | 'examples'
    surface: 'agent' | 'voice_playground' | 'blind_test'
    description?: string
    examples?: Array<{ transcript: string; rating: any; notes?: string }>
  }): Promise<{
    name: string
    description: string
    metric_type: 'rating' | 'boolean' | 'number' | 'text'
    custom_data_type: 'boolean' | 'enum' | 'number_range' | null
    custom_config: Record<string, any>
    supported_surfaces: string[]
    enabled_surfaces: string[]
    suggested_tags: string[]
  }> {
    const response = await this.client.post('/api/v1/metrics/generate', data)
    return response.data
  }

  async parseBulkMetric(data: {
    prompt: string
    surface: 'agent' | 'voice_playground' | 'blind_test'
    /** When set, the response includes a ``parent`` block + all labels are children. */
    parent_name?: string
    parent_description?: string
    selection_mode?: 'single_choice' | 'multi_label'
  }): Promise<{
    metrics: Array<{
      name: string
      description: string
      metric_type: 'rating' | 'boolean' | 'number' | 'text'
      custom_data_type: 'boolean' | 'enum' | 'number_range' | null
      custom_config: Record<string, any>
      supported_surfaces: string[]
      enabled_surfaces: string[]
      capture_rationale: boolean
      suggested_tags: string[]
      source_label: { label_name: string; definition: string; examples: string }
    }>
    parent?: {
      name: string
      description: string | null
      selection_mode: 'single_choice' | 'multi_label'
      supported_surfaces: string[]
      enabled_surfaces: string[]
    } | null
  }> {
    const response = await this.client.post('/api/v1/metrics/parse-bulk', data)
    return response.data
  }

  // Alert endpoints
  async listAlerts(status?: string): Promise<any[]> {
    const params: any = {}
    if (status) {
      params.status_filter = status
    }
    const response = await this.client.get('/api/v1/alerts', { params })
    return response.data
  }

  async getAlert(alertId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/alerts/${alertId}`)
    return response.data
  }

  async createAlert(data: {
    name: string
    description?: string | null
    metric_type: string
    aggregation: string
    operator: string
    threshold_value: number
    time_window_minutes: number
    agent_ids?: string[] | null
    notify_frequency: string
    notify_emails?: string[]
    notify_webhooks?: string[]
  }): Promise<any> {
    const response = await this.client.post('/api/v1/alerts', data)
    return response.data
  }

  async updateAlert(alertId: string, data: {
    name?: string
    description?: string | null
    metric_type?: string
    aggregation?: string
    operator?: string
    threshold_value?: number
    time_window_minutes?: number
    agent_ids?: string[] | null
    notify_frequency?: string
    notify_emails?: string[]
    notify_webhooks?: string[]
    status?: string
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/alerts/${alertId}`, data)
    return response.data
  }

  async deleteAlert(alertId: string): Promise<void> {
    await this.client.delete(`/api/v1/alerts/${alertId}`)
  }

  async toggleAlertStatus(alertId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/alerts/${alertId}/toggle`)
    return response.data
  }

  // Alert History endpoints
  async listAlertHistory(status?: string, alertId?: string, skip = 0, limit = 100): Promise<any[]> {
    const params: any = { skip, limit }
    if (status) {
      params.status_filter = status
    }
    if (alertId) {
      params.alert_id = alertId
    }
    const response = await this.client.get('/api/v1/alerts/history/all', { params })
    return response.data
  }

  async getAlertHistoryItem(historyId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/alerts/history/${historyId}`)
    return response.data
  }

  async acknowledgeAlertHistory(historyId: string): Promise<any> {
    const response = await this.client.put(`/api/v1/alerts/history/${historyId}`, {
      status: 'acknowledged'
    })
    return response.data
  }

  async resolveAlertHistory(historyId: string, resolutionNotes?: string): Promise<any> {
    const response = await this.client.put(`/api/v1/alerts/history/${historyId}`, {
      status: 'resolved',
      resolution_notes: resolutionNotes
    })
    return response.data
  }

  // Alert Evaluation & Notification endpoints
  async triggerAlert(alertId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/alerts/${alertId}/trigger`)
    return response.data
  }

  async evaluateAllAlerts(): Promise<any> {
    const response = await this.client.post('/api/v1/alerts/evaluate/all')
    return response.data
  }

  async testAlertNotification(alertId: string, data: {
    webhook_url?: string
    email?: string
  }): Promise<any> {
    const response = await this.client.post(`/api/v1/alerts/${alertId}/test-notification`, data)
    return response.data
  }

  // Cron Job endpoints
  async listCronJobs(): Promise<any[]> {
    const response = await this.client.get('/api/v1/cron-jobs')
    return response.data
  }

  async getCronJob(cronJobId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/cron-jobs/${cronJobId}`)
    return response.data
  }

  async createCronJob(data: {
    name: string
    cron_expression: string
    timezone: string
    max_runs: number
    evaluator_ids: string[]
  }): Promise<any> {
    const response = await this.client.post('/api/v1/cron-jobs', data)
    return response.data
  }

  async updateCronJob(cronJobId: string, data: {
    name?: string
    cron_expression?: string
    timezone?: string
    max_runs?: number
    evaluator_ids?: string[]
    status?: string
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/cron-jobs/${cronJobId}`, data)
    return response.data
  }

  async deleteCronJob(cronJobId: string): Promise<void> {
    await this.client.delete(`/api/v1/cron-jobs/${cronJobId}`)
  }

  async toggleCronJobStatus(cronJobId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/cron-jobs/${cronJobId}/toggle`)
    return response.data
  }

  // Voice Playground (TTS Comparison) endpoints
  async listTTSProviders(): Promise<any[]> {
    const response = await this.client.get('/api/v1/voice-playground/tts-providers')
    return response.data
  }

  async listCustomTTSVoices(provider?: string): Promise<Array<{
    id: string
    provider: string
    voice_id: string
    name: string
    gender: string
    accent: string
    description?: string | null
    is_custom: boolean
    created_at?: string | null
    updated_at?: string | null
  }>> {
    const response = await this.client.get('/api/v1/voice-playground/custom-voices', {
      params: provider ? { provider } : undefined,
    })
    return response.data
  }

  async createCustomTTSVoice(data: {
    provider: string
    voice_id: string
    name: string
    gender?: string
    accent?: string
    description?: string
  }): Promise<any> {
    const response = await this.client.post('/api/v1/voice-playground/custom-voices', data)
    return response.data
  }

  async updateCustomTTSVoice(customVoiceId: string, data: {
    voice_id?: string
    name?: string
    gender?: string
    accent?: string
    description?: string
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/voice-playground/custom-voices/${customVoiceId}`, data)
    return response.data
  }

  async deleteCustomTTSVoice(customVoiceId: string): Promise<any> {
    const response = await this.client.delete(`/api/v1/voice-playground/custom-voices/${customVoiceId}`)
    return response.data
  }

  async createTTSComparison(data: {
    name?: string
    mode?: 'benchmark' | 'blind_test_only'
    // Legacy benchmark fields
    provider_a?: string
    model_a?: string
    voices_a?: Array<{ id: string; name: string; sample_rate_hz?: number }>
    provider_b?: string
    model_b?: string
    voices_b?: Array<{ id: string; name: string; sample_rate_hz?: number }>
    // New per-side benchmark config
    side_a?: VoicePlaygroundSideConfig
    side_b?: VoicePlaygroundSideConfig
    // Common
    sample_texts?: string[]
    num_runs?: number
    eval_stt_provider?: string
    eval_stt_model?: string
    // blind_test_only
    pairs?: Array<VoicePlaygroundBlindTestPair>
  }): Promise<any> {
    const response = await this.client.post('/api/v1/voice-playground/comparisons', data)
    return response.data
  }

  async listVoicePlaygroundCallImportRows(params: {
    call_import_id?: string
    with_recording?: boolean
    skip?: number
    limit?: number
  } = {}): Promise<{
    items: Array<{
      id: string
      call_import_id: string
      call_import_filename: string | null
      conversation_id: string
      transcript: string | null
      recording_s3_key: string | null
      has_recording: boolean
      status: string
      created_at: string | null
    }>
    total: number
    skip: number
    limit: number
  }> {
    const response = await this.client.get('/api/v1/voice-playground/call-import-rows', { params })
    return response.data
  }

  async uploadVoicePlaygroundAudio(file: File): Promise<{
    s3_key: string
    presigned_url: string | null
    filename: string
    size_bytes: number
    content_type: string
  }> {
    const form = new FormData()
    form.append('file', file)
    const response = await this.client.post('/api/v1/voice-playground/uploads', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async listTTSComparisons(skip = 0, limit = 50): Promise<any[]> {
    const response = await this.client.get('/api/v1/voice-playground/comparisons', {
      params: { skip, limit },
    })
    return response.data
  }

  async getTTSComparison(comparisonId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/voice-playground/comparisons/${comparisonId}`)
    return response.data
  }

  async generateTTSComparison(comparisonId: string): Promise<{ message: string; task_id: string }> {
    const response = await this.client.post(`/api/v1/voice-playground/comparisons/${comparisonId}/generate`)
    return response.data
  }

  async submitBlindTest(comparisonId: string, results: Array<{
    sample_index: number
    preferred: 'A' | 'B'
    voice_a_id: string
    voice_b_id: string
  }>): Promise<any> {
    const response = await this.client.post(
      `/api/v1/voice-playground/comparisons/${comparisonId}/blind-test`,
      { results }
    )
    return response.data
  }

  async deleteTTSComparison(comparisonId: string): Promise<void> {
    await this.client.delete(`/api/v1/voice-playground/comparisons/${comparisonId}`)
  }

  // Blind Test Sharing (owner side)
  async createBlindTestShare(comparisonId: string, payload: {
    title: string
    description?: string
    creator_notes?: string
    custom_metrics: Array<{ key: string; label: string; type: 'rating' | 'comment'; scale?: number }>
  }): Promise<any> {
    const response = await this.client.post(
      `/api/v1/voice-playground/comparisons/${comparisonId}/share`,
      payload
    )
    return response.data
  }

  async getBlindTestShare(comparisonId: string): Promise<any> {
    const response = await this.client.get(
      `/api/v1/voice-playground/comparisons/${comparisonId}/share`
    )
    return response.data
  }

  async updateBlindTestShare(shareId: string, payload: {
    title?: string
    description?: string
    creator_notes?: string
    custom_metrics?: Array<{ key: string; label: string; type: 'rating' | 'comment'; scale?: number }>
    status?: 'open' | 'closed'
  }): Promise<any> {
    const response = await this.client.patch(
      `/api/v1/voice-playground/shares/${shareId}`,
      payload
    )
    return response.data
  }

  async deleteBlindTestShare(shareId: string): Promise<void> {
    await this.client.delete(`/api/v1/voice-playground/shares/${shareId}`)
  }

  async listBlindTestResponses(shareId: string, skip = 0, limit = 100): Promise<{
    items: any[]
    total: number
  }> {
    const response = await this.client.get(
      `/api/v1/voice-playground/shares/${shareId}/responses`,
      { params: { skip, limit } }
    )
    return response.data
  }

  async generateSampleTexts(params: {
    voice_bundle_id?: string
    provider?: string
    model?: string
    scenario?: string
    count?: number
    length?: string
    temperature?: number
  }): Promise<{ samples: string[]; provider: string; model: string }> {
    const response = await this.client.post('/api/v1/voice-playground/generate-samples', params)
    return response.data
  }

  async getTTSAnalytics(): Promise<Array<{
    provider: string
    model: string
    voice_id: string
    voice_name: string
    sample_count: number
    avg_mos: number | null
    avg_valence: number | null
    avg_arousal: number | null
    avg_prosody: number | null
    avg_ttfb_ms: number | null
    avg_latency_ms: number | null
    avg_wer: number | null
    avg_cer: number | null
  }>> {
    const response = await this.client.get('/api/v1/voice-playground/analytics')
    return response.data
  }

  async downloadTTSComparisonReport(
    comparisonId: string,
    includeUnfinishedSamples = false,
    reportOptions?: TTSReportOptionsPayload
  ): Promise<Blob> {
    const response = await this.client.get(
      `/api/v1/voice-playground/comparisons/${comparisonId}/report.pdf`,
      {
        params: {
          include_unfinished_samples: includeUnfinishedSamples,
          ...(reportOptions ? { report_options: JSON.stringify(reportOptions) } : {}),
        },
        responseType: 'blob',
      }
    )
    return response.data
  }

  async createTTSComparisonReportJob(
    comparisonId: string,
    reportOptions?: TTSReportOptionsPayload
  ): Promise<{
    id: string
    comparison_id: string
    status: string
    format: string
    task_id?: string
    report_options?: TTSReportOptionsPayload
    created_at?: string | null
  }> {
    const response = await this.client.post(
      `/api/v1/voice-playground/comparisons/${comparisonId}/reports`,
      reportOptions ? { report_options: reportOptions } : {}
    )
    return response.data
  }

  async getVoicePlaygroundReportThresholdDefaults(): Promise<{
    zone_threshold_overrides: NonNullable<TTSReportOptionsPayload['zone_threshold_overrides']>
    is_custom: boolean
  }> {
    const response = await this.client.get('/api/v1/voice-playground/report-threshold-defaults')
    return response.data
  }

  async updateVoicePlaygroundReportThresholdDefaults(data: {
    zone_threshold_overrides?: NonNullable<TTSReportOptionsPayload['zone_threshold_overrides']>
    reset_to_system_defaults?: boolean
  }): Promise<{
    zone_threshold_overrides: NonNullable<TTSReportOptionsPayload['zone_threshold_overrides']>
    is_custom: boolean
    message: string
  }> {
    const response = await this.client.put('/api/v1/voice-playground/report-threshold-defaults', data)
    return response.data
  }

  async getTTSComparisonReportJob(reportJobId: string): Promise<{
    id: string
    comparison_id: string
    status: string
    format: string
    filename?: string | null
    error_message?: string | null
    task_id?: string | null
    download_url?: string | null
    report_options?: TTSReportOptionsPayload
    created_at?: string | null
    updated_at?: string | null
  }> {
    const response = await this.client.get(`/api/v1/voice-playground/reports/${reportJobId}`)
    return response.data
  }

  // Prompt Partials
  async listPromptPartials(skip = 0, limit = 100, search?: string): Promise<any[]> {
    const response = await this.client.get('/api/v1/prompt-partials', {
      params: { skip, limit, ...(search ? { search } : {}) },
    })
    return response.data
  }

  async getPromptPartial(partialId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/prompt-partials/${partialId}`)
    return response.data
  }

  async createPromptPartial(data: {
    name: string
    description?: string
    content: string
    tags?: string[]
  }): Promise<any> {
    const response = await this.client.post('/api/v1/prompt-partials', data)
    return response.data
  }

  async updatePromptPartial(partialId: string, data: {
    name?: string
    description?: string
    content?: string
    tags?: string[]
    change_summary?: string
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/prompt-partials/${partialId}`, data)
    return response.data
  }

  async deletePromptPartial(partialId: string): Promise<void> {
    await this.client.delete(`/api/v1/prompt-partials/${partialId}`)
  }

  async listPromptPartialVersions(partialId: string): Promise<any[]> {
    const response = await this.client.get(`/api/v1/prompt-partials/${partialId}/versions`)
    return response.data
  }

  async getPromptPartialVersion(partialId: string, versionNumber: number): Promise<any> {
    const response = await this.client.get(`/api/v1/prompt-partials/${partialId}/versions/${versionNumber}`)
    return response.data
  }

  async revertPromptPartial(partialId: string, versionNumber: number): Promise<any> {
    const response = await this.client.post(`/api/v1/prompt-partials/${partialId}/revert/${versionNumber}`)
    return response.data
  }

  async clonePromptPartial(partialId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/prompt-partials/${partialId}/clone`)
    return response.data
  }

  async generatePromptWithAI(data: {
    description: string
    tone?: string
    format_style?: string
    provider?: string
    model?: string
  }): Promise<{ content: string; provider: string; model: string }> {
    const response = await this.client.post('/api/v1/prompt-partials/generate', data)
    return response.data
  }

  async improvePromptWithAI(data: {
    content: string
    instructions?: string
    provider?: string
    model?: string
  }): Promise<{ content: string; provider: string; model: string }> {
    const response = await this.client.post('/api/v1/prompt-partials/improve', data)
    return response.data
  }

  // License / Enterprise
  async getLicenseInfo(): Promise<LicenseInfoResponse> {
    const response = await this.client.get('/api/v1/settings/license-info')
    return response.data
  }

  async getReportBranding(): Promise<ReportBranding> {
    const response = await this.client.get('/api/v1/settings/report-branding')
    return response.data
  }

  async updateReportBranding(data: { heading?: string | null }): Promise<ReportBranding> {
    const response = await this.client.patch('/api/v1/settings/report-branding', data)
    return response.data
  }

  async uploadReportBrandingImages(
    files: File[],
    role: 'internal' | 'external' | 'generic' = 'generic',
  ): Promise<ReportBranding> {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    formData.append('role', role)
    const response = await this.client.post('/api/v1/settings/report-branding/images', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async deleteReportBrandingImage(imageId: string): Promise<ReportBranding> {
    const response = await this.client.delete(`/api/v1/settings/report-branding/images/${imageId}`)
    return response.data
  }

  // GEPA Prompt Optimization (Enterprise)
  async createOptimizationRun(data: {
    agent_id: string
    evaluator_id?: string
    voice_bundle_id?: string
    config?: Record<string, any>
  }): Promise<any> {
    const response = await this.client.post('/api/v1/prompt-optimization/runs', data)
    return response.data
  }

  async deleteOptimizationRun(runId: string): Promise<void> {
    await this.client.delete(`/api/v1/prompt-optimization/runs/${runId}`)
  }

  async listOptimizationRuns(agentId?: string): Promise<any[]> {
    const params = agentId ? { agent_id: agentId } : {}
    const response = await this.client.get('/api/v1/prompt-optimization/runs', { params })
    return response.data
  }

  async getOptimizationRun(runId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/prompt-optimization/runs/${runId}`)
    return response.data
  }

  async listOptimizationCandidates(runId: string): Promise<any[]> {
    const response = await this.client.get(`/api/v1/prompt-optimization/runs/${runId}/candidates`)
    return response.data
  }

  async acceptCandidate(runId: string, candidateId: string): Promise<any> {
    const response = await this.client.post(
      `/api/v1/prompt-optimization/runs/${runId}/candidates/${candidateId}/accept`
    )
    return response.data
  }

  async pushCandidateToProvider(runId: string, candidateId: string): Promise<any> {
    const response = await this.client.post(
      `/api/v1/prompt-optimization/runs/${runId}/candidates/${candidateId}/push`
    )
    return response.data
  }

  async syncProviderPrompt(agentId: string): Promise<{
    synced: boolean
    provider_prompt: string | null
    provider_prompt_synced_at: string | null
  }> {
    const response = await this.client.post(`/api/v1/agents/${agentId}/sync-provider-prompt`)
    return response.data
  }

  // -------------------------------------------------------------------
  // Judge Alignment (AlignEval-style hybrid integration)
  //
  // Per-org thresholds and judge model selection are sourced from the
  // backend (no hardcoded defaults in the frontend).
  // -------------------------------------------------------------------

  async getJudgeAlignmentSettings(): Promise<JudgeAlignmentSettings> {
    const response = await this.client.get('/api/v1/judge-alignment/settings')
    return response.data
  }

  async updateJudgeAlignmentSettings(
    data: { min_labels_to_evaluate: number; min_labels_to_optimize: number }
  ): Promise<JudgeAlignmentSettings> {
    const response = await this.client.patch('/api/v1/judge-alignment/settings', data)
    return response.data
  }

  async listJudgeCapableModels(): Promise<JudgeModelCatalogEntry[]> {
    const response = await this.client.get('/api/v1/judge-alignment/available-models')
    return response.data
  }

  async listJudgeDatasets(): Promise<JudgeDataset[]> {
    const response = await this.client.get('/api/v1/judge-alignment/datasets')
    return response.data
  }

  async createJudgeDataset(data: {
    name: string
    description?: string
    source_type: 'transcript' | 'metric_output' | 'csv'
    source_config?: Record<string, any>
    input_field?: string
    output_field?: string
  }): Promise<JudgeDataset> {
    const response = await this.client.post('/api/v1/judge-alignment/datasets', data)
    return response.data
  }

  async uploadJudgeDatasetCsv(
    file: File,
    name: string,
    description?: string
  ): Promise<JudgeDataset> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', name)
    if (description) formData.append('description', description)
    const response = await this.client.post(
      '/api/v1/judge-alignment/datasets/upload-csv',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    return response.data
  }

  async getJudgeDataset(datasetId: string): Promise<JudgeDataset> {
    const response = await this.client.get(`/api/v1/judge-alignment/datasets/${datasetId}`)
    return response.data
  }

  async deleteJudgeDataset(datasetId: string): Promise<void> {
    await this.client.delete(`/api/v1/judge-alignment/datasets/${datasetId}`)
  }

  async listJudgeSamples(
    datasetId: string,
    options: { only_labeled?: boolean; skip?: number; limit?: number } = {}
  ): Promise<JudgeSample[]> {
    const response = await this.client.get(
      `/api/v1/judge-alignment/datasets/${datasetId}/samples`,
      { params: options }
    )
    return response.data
  }

  async labelJudgeSample(
    sampleId: string,
    label: 'pass' | 'fail' | null
  ): Promise<JudgeSample> {
    const response = await this.client.patch(
      `/api/v1/judge-alignment/samples/${sampleId}`,
      { label }
    )
    return response.data
  }

  async bulkLabelJudgeSamples(
    datasetId: string,
    items: Array<{ sample_id: string; label: 'pass' | 'fail' | null }>
  ): Promise<{ updated: number; requested: number }> {
    const response = await this.client.post(
      `/api/v1/judge-alignment/datasets/${datasetId}/samples/bulk-label`,
      { items }
    )
    return response.data
  }

  async listJudgeRuns(datasetId: string): Promise<JudgeRun[]> {
    const response = await this.client.get(
      `/api/v1/judge-alignment/datasets/${datasetId}/runs`
    )
    return response.data
  }

  async triggerJudgeRun(
    datasetId: string,
    data: { evaluator_id: string; split?: 'all' | 'dev' | 'test'; sample_ids?: string[] }
  ): Promise<JudgeRun> {
    const response = await this.client.post(
      `/api/v1/judge-alignment/datasets/${datasetId}/run`,
      data
    )
    return response.data
  }

  async getJudgeRun(runId: string): Promise<JudgeRun> {
    const response = await this.client.get(`/api/v1/judge-alignment/runs/${runId}`)
    return response.data
  }

  async recomputeJudgeRunMetrics(runId: string): Promise<JudgeRun> {
    const response = await this.client.post(
      `/api/v1/judge-alignment/runs/${runId}/recompute-metrics`
    )
    return response.data
  }

  async deleteJudgeRun(runId: string): Promise<void> {
    await this.client.delete(`/api/v1/judge-alignment/runs/${runId}`)
  }

  async optimizeJudge(
    datasetId: string,
    data: {
      evaluator_id: string
      dev_ratio?: number
      seed?: number
      max_metric_calls?: number
      minibatch_size?: number
      agent_id?: string
    }
  ): Promise<JudgeOptimizeResponse> {
    const response = await this.client.post(
      `/api/v1/judge-alignment/datasets/${datasetId}/optimize`,
      data
    )
    return response.data
  }
}

// -------------------------------------------------------------------
// Judge Alignment shared types
// -------------------------------------------------------------------

export interface JudgeAlignmentSettings {
  min_labels_to_evaluate: number
  min_labels_to_optimize: number
  defaults: { min_labels_to_evaluate: number; min_labels_to_optimize: number }
}

export interface JudgeModelCatalogEntry {
  provider: string
  provider_label: string
  model: string
  label: string
}

export interface JudgeDataset {
  id: string
  name: string
  description?: string | null
  source_type: 'transcript' | 'metric_output' | 'csv'
  source_config: Record<string, any>
  input_field: string
  output_field: string
  total_samples: number
  labeled_samples: number
  unlabeled_samples: number
  created_at?: string
  updated_at?: string
}

export interface JudgeSample {
  id: string
  dataset_id: string
  external_id?: string | null
  input_text: string
  output_text: string
  label?: 'pass' | 'fail' | null
  labeled_by?: string | null
  labeled_at?: string | null
  extra?: Record<string, any> | null
  created_at?: string
}

export interface JudgeRunMetrics {
  precision: number
  recall: number
  f1: number
  kappa: number
  tp: number
  fp: number
  tn: number
  fn: number
  n: number
}

export interface JudgeRun {
  id: string
  dataset_id: string
  evaluator_id?: string | null
  split: 'all' | 'dev' | 'test'
  llm_provider?: string | null
  llm_model?: string | null
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed'
  metrics?: JudgeRunMetrics | null
  predictions?: Record<string, { prediction: 'pass' | 'fail' | null; explanation?: string; raw?: string }> | null
  error_message?: string | null
  celery_task_id?: string | null
  gepa_optimization_id?: string | null
  created_at?: string
  updated_at?: string
}

export interface JudgeOptimizeResponse {
  optimization_run_id: string
  dev_sample_count: number
  test_sample_count: number
}

// Factory function to create ApiClient instance
// This ensures TypeScript correctly infers the type as ApiClient, not AxiosInstance
function createApiClient(): ApiClient {
  return new ApiClient()
}

// Create instance
const apiClientInstance = createApiClient()

// Export with explicit type annotation - CRITICAL for TypeScript to recognize as ApiClient
// Without this explicit type, TypeScript may incorrectly infer AxiosInstance
export const apiClient: ApiClient = apiClientInstance

// Re-export the type for explicit typing if needed
export type { ApiClient }


// ----------------------------------------------------------------------
// Public (unauthenticated) blind-test API.
// Uses a bare axios instance so no Authorization / X-API-Key headers are
// attached. Anyone with the share_token in the URL can call these.
// ----------------------------------------------------------------------

const publicClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

export interface PublicBlindTestEntrySubmit {
  sample_index: number
  preferred: 'X' | 'Y'
  ratings_x?: Record<string, number>
  ratings_y?: Record<string, number>
  comment?: string
}

export const publicBlindTestApi = {
  async getForm(shareToken: string): Promise<any> {
    const res = await publicClient.get(`/api/v1/public/blind-tests/${shareToken}`)
    return res.data
  },
  async submit(shareToken: string, payload: {
    rater_name: string
    rater_email: string
    client_token: string
    responses: PublicBlindTestEntrySubmit[]
  }): Promise<any> {
    const res = await publicClient.post(
      `/api/v1/public/blind-tests/${shareToken}/responses`,
      payload
    )
    return res.data
  },
}
