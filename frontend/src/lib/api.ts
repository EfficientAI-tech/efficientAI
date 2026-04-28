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
  CallImportDetail,
  CallImportListResponse,
  CallImportStatus,
  CallImportUploadResponse,
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
  verify_app_uuid?: string | null
  voice_app_id?: string | null
  sip_domain?: string | null
  masking_config?: Record<string, any> | null
  is_active: boolean
  last_tested_at?: string | null
  created_at: string
  updated_at: string
}

export interface TelephonyIntegrationCreatePayload {
  provider?: string
  auth_id: string
  auth_token: string
  verify_app_uuid?: string
  voice_app_id?: string
  sip_domain?: string
  masking_config?: Record<string, any>
}

export interface TelephonyIntegrationUpdatePayload {
  provider?: string
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

    // Add request interceptor to add API key to headers
    this.client.interceptors.request.use((config) => {
      const accessToken = localStorage.getItem('accessToken')
      const apiKey = localStorage.getItem('apiKey')
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

  async updateTelephonyConfig(data: TelephonyIntegrationUpdatePayload): Promise<TelephonyIntegrationResponse> {
    const response = await this.client.put('/api/v1/telephony/config', data)
    return response.data
  }

  async testTelephonyConfig(provider: string = 'plivo'): Promise<{ success: boolean }> {
    const response = await this.client.post('/api/v1/telephony/config/test', null, { params: { provider } })
    return response.data
  }

  async syncTelephonyNumbers(provider: string = 'plivo'): Promise<TelephonyPhoneNumberResponse[]> {
    const response = await this.client.post('/api/v1/telephony/numbers/sync', null, {
      params: { provider },
    })
    return response.data
  }

  async listTelephonyNumbers(provider?: string): Promise<TelephonyPhoneNumberResponse[]> {
    const response = await this.client.get('/api/v1/telephony/numbers', {
      params: provider ? { provider } : undefined,
    })
    return response.data
  }

  async updateTelephonyNumber(
    numberId: string,
    data: { is_masking_pool?: boolean; agent_id?: string | null; is_active?: boolean }
  ): Promise<TelephonyPhoneNumberResponse> {
    const response = await this.client.patch(`/api/v1/telephony/numbers/${numberId}`, data)
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
  async uploadCallImport(file: File): Promise<CallImportUploadResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await this.client.post('/api/v1/call-imports/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async listCallImports(
    params: { page?: number; page_size?: number; status?: CallImportStatus } = {}
  ): Promise<CallImportListResponse> {
    const response = await this.client.get('/api/v1/call-imports', { params })
    return response.data
  }

  async getCallImport(
    id: string,
    params: { row_limit?: number; row_offset?: number } = {}
  ): Promise<CallImportDetail> {
    const response = await this.client.get(`/api/v1/call-imports/${id}`, { params })
    return response.data
  }

  async deleteCallImport(id: string): Promise<void> {
    await this.client.delete(`/api/v1/call-imports/${id}`)
  }

  async deleteCallImportRow(id: string, rowId: string): Promise<void> {
    await this.client.delete(`/api/v1/call-imports/${id}/rows/${rowId}`)
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
    metric_type: 'number' | 'boolean' | 'rating'
    trigger?: 'always'
    enabled?: boolean
    metric_origin?: 'default' | 'custom'
    supported_surfaces?: string[]
    enabled_surfaces?: string[]
    custom_data_type?: 'boolean' | 'enum' | 'number_range'
    custom_config?: Record<string, any>
    tags?: string[]
  }): Promise<any> {
    const response = await this.client.post('/api/v1/metrics', data)
    return response.data
  }

  async listMetrics(surface?: string): Promise<any[]> {
    const response = await this.client.get('/api/v1/metrics', {
      params: surface ? { surface } : undefined,
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
    metric_type?: 'number' | 'boolean' | 'rating'
    trigger?: 'always'
    enabled?: boolean
    metric_origin?: 'default' | 'custom'
    supported_surfaces?: string[]
    enabled_surfaces?: string[]
    custom_data_type?: 'boolean' | 'enum' | 'number_range'
    custom_config?: Record<string, any>
    tags?: string[]
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
      external_call_id: string
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

