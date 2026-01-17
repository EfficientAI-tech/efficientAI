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
  Role,
  Integration,
  IntegrationCreate,
  S3ConnectionTestResponse,
  S3ListFilesResponse,
  S3Status,
} from '../types/api'

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

  async deleteAgent(agentId: string): Promise<void> {
    await this.client.delete(`/api/v1/agents/${agentId}`)
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

  async deletePersona(personaId: string): Promise<void> {
    await this.client.delete(`/api/v1/personas/${personaId}`)
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
    description?: string | null
    required_info: Record<string, string>
  }): Promise<any> {
    const response = await this.client.post('/api/v1/scenarios', data)
    return response.data
  }

  async updateScenario(scenarioId: string, data: any): Promise<any> {
    const response = await this.client.put(`/api/v1/scenarios/${scenarioId}`, data)
    return response.data
  }

  async deleteScenario(scenarioId: string): Promise<void> {
    await this.client.delete(`/api/v1/scenarios/${scenarioId}`)
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

  async deleteVoiceBundle(voicebundleId: string): Promise<void> {
    await this.client.delete(`/api/v1/voicebundles/${voicebundleId}`)
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

  async deleteIntegration(integrationId: string): Promise<void> {
    await this.client.delete(`/api/v1/integrations/${integrationId}`)
  }

  async testIntegration(integrationId: string): Promise<MessageResponse> {
    const response = await this.client.post(`/api/v1/integrations/${integrationId}/test`)
    return response.data
  }

  async getIntegrationApiKey(integrationId: string): Promise<{ api_key: string; public_key?: string | null }> {
    const response = await this.client.get(`/api/v1/integrations/${integrationId}/api-key`)
    return response.data
  }

  // Data Sources endpoints
  async testS3Connection(): Promise<S3ConnectionTestResponse> {
    const response = await this.client.post('/api/v1/data-sources/s3/test-connection')
    return response.data
  }

  async listS3Files(prefix?: string, maxKeys = 1000): Promise<S3ListFilesResponse> {
    const response = await this.client.get('/api/v1/data-sources/s3/files', {
      params: { prefix, max_keys: maxKeys },
    })
    return response.data
  }

  async uploadToS3(file: File, customFilename?: string): Promise<AudioFile> {
    const formData = new FormData()
    formData.append('file', file)
    if (customFilename) {
      formData.append('custom_filename', customFilename)
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

  async getModelOptions(provider: string): Promise<{ stt: string[]; llm: string[]; tts: string[]; s2s: string[] }> {
    const response = await this.client.get(`/api/v1/model-config/providers/${provider}/options`)
    const data = response.data
    // Ensure s2s is always present (for backward compatibility)
    return {
      ...data,
      s2s: data.s2s || []
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

  // Evaluator endpoints
  async createEvaluator(data: {
    agent_id: string
    persona_id: string
    scenario_id: string
    tags?: string[]
  }): Promise<any> {
    const response = await this.client.post('/api/v1/evaluators', data)
    return response.data
  }

  async createEvaluatorsBulk(data: {
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
    tags?: string[]
  }): Promise<any> {
    const response = await this.client.put(`/api/v1/evaluators/${evaluatorId}`, data)
    return response.data
  }

  async deleteEvaluator(evaluatorId: string): Promise<void> {
    await this.client.delete(`/api/v1/evaluators/${evaluatorId}`)
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
  async listEvaluatorResults(evaluatorId?: string, playground?: boolean): Promise<any[]> {
    const params: any = {}
    if (evaluatorId) {
      params.evaluator_id = evaluatorId
    }
    if (playground !== undefined) {
      params.playground = playground
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

