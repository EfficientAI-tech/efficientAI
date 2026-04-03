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
} from '../types/api'

export interface EnterpriseFeatureMeta {
  title: string
  description?: string
  category?: string
}

export type EnterpriseFeatureCatalog = Record<string, EnterpriseFeatureMeta>

export interface LicenseInfoResponse {
  is_enterprise: boolean
  enabled_features: string[]
  all_enterprise_features: string[]
  feature_catalog?: EnterpriseFeatureCatalog
  organization?: string
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
      const apiKey = localStorage.getItem('apiKey')
      if (apiKey) {
        config.headers['X-API-Key'] = apiKey
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

  // Auth endpoints
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
    language?: string
    description?: string | null
    call_type?: string
    call_medium?: string
    voice_bundle_id?: string
    ai_provider_id?: string
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
    language: string
    accent: string
    gender: string
    background_noise: string
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
    access_token: string
    call_id: string
    agent_id: string
    agent_version?: number
    call_status: string
    agent_name?: string
    metadata?: Record<string, any>
    retell_llm_dynamic_variables?: Record<string, any>
    sample_rate?: number
    call_short_id?: string
    signed_url?: string
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
  }): Promise<any> {
    const response = await this.client.post('/api/v1/metrics', data)
    return response.data
  }

  async listMetrics(): Promise<any[]> {
    const response = await this.client.get('/api/v1/metrics')
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
    provider_a: string
    model_a: string
    voices_a: Array<{ id: string; name: string; sample_rate_hz?: number }>
    provider_b?: string
    model_b?: string
    voices_b?: Array<{ id: string; name: string; sample_rate_hz?: number }>
    sample_texts: string[]
    num_runs?: number
  }): Promise<any> {
    const response = await this.client.post('/api/v1/voice-playground/comparisons', data)
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

