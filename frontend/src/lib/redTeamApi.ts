import type { AxiosInstance } from 'axios'
import type {
  RedTeamAttackDetail,
  RedTeamEntitlements,
  RedTeamLaunchResponse,
  RedTeamRun,
  RedTeamRunCreate,
  RedTeamRunDetail,
} from '../types/redTeam'

/** Red team runs; exposed as `apiClient.redTeam`. `runRef` is the 6-digit run_id or the uuid. */
export class RedTeamApi {
  constructor(private readonly client: AxiosInstance) {}

  async getEntitlements(): Promise<RedTeamEntitlements> {
    const response = await this.client.get('/api/v1/red-team-runs/entitlements')
    return response.data
  }

  async listRuns(agentId: string, limit = 50): Promise<RedTeamRun[]> {
    const response = await this.client.get('/api/v1/red-team-runs', { params: { agent_id: agentId, limit } })
    return response.data
  }

  /** `confirmed: false` returns the preview only; `confirmed: true` creates the run. */
  async launchRun(data: RedTeamRunCreate): Promise<RedTeamLaunchResponse> {
    const response = await this.client.post('/api/v1/red-team-runs', data)
    return response.data
  }

  async getRun(runRef: string): Promise<RedTeamRunDetail> {
    const response = await this.client.get(`/api/v1/red-team-runs/${runRef}`)
    return response.data
  }

  async getAttack(runRef: string, attackId: string): Promise<RedTeamAttackDetail> {
    const response = await this.client.get(`/api/v1/red-team-runs/${runRef}/attacks/${attackId}`)
    return response.data
  }

  async stopRun(runRef: string): Promise<RedTeamRun> {
    const response = await this.client.post(`/api/v1/red-team-runs/${runRef}/stop`)
    return response.data
  }

  async deleteRun(runRef: string): Promise<void> {
    await this.client.delete(`/api/v1/red-team-runs/${runRef}`)
  }

  async downloadReport(runRef: string, format: 'pdf' | 'csv'): Promise<Blob> {
    const response = await this.client.get(`/api/v1/red-team-runs/${runRef}/report.${format}`, {
      responseType: 'blob',
    })
    return response.data
  }
}
