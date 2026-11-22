import type { AxiosInstance } from 'axios'

export interface CopilotReason {
  code: string
  message: string
}

export interface CopilotStatus {
  ready: boolean
  reasons: CopilotReason[]
  warnings: CopilotReason[]
  provider: string | null
  model: string | null
  credential_name: string | null
  tool_calling: 'supported' | 'unsupported' | 'unknown' | null
  tools: string[]
}

export interface CopilotSession {
  id: string
  title: string | null
  status: 'active' | 'archived'
  message_count: number
  last_message_at: string | null
  created_at: string
  draft?: Record<string, unknown> | null
}

export interface CopilotToolCall {
  id: string
  name: string
  status: string
  latency_ms?: number | null
  ui?: CopilotCard | null
}

export type CopilotMessageStatus = 'streaming' | 'complete' | 'failed' | 'cancelled' | 'interrupted'

export interface CopilotMessage {
  id: string
  seq: number
  role: 'user' | 'assistant' | 'event'
  content: string
  status: CopilotMessageStatus
  error?: string | null
  tool_calls: CopilotToolCall[]
  created_at: string
}

export interface TestSetupDraft {
  kind: 'test_setup'
  agent_id: string | null
  agent_name: string
  sections: { key: string; title: string; content: string }[]
  test_agent_prompt: string
  first_message: { caller_message: string | null; production_message: string | null }
  scenarios: { name: string; description: string; goal?: string | null }[]
  saved: boolean
}

export interface CopilotDraftCard {
  type: 'draft'
  draft: TestSetupDraft
}

export type CopilotActionStatus =
  | 'proposed'
  | 'applying'
  | 'applied'
  | 'failed'
  | 'rejected'
  | 'expired'
  | 'undoing'
  | 'undone'

export interface CopilotEntityRef {
  type: string
  id: string
  name?: string
  link?: string
}

export interface CopilotAction {
  id: string
  kind: string
  title: string
  status: CopilotActionStatus
  summary: string
  payload: Record<string, unknown>
  payload_schema: Record<string, unknown> | null
  costly: boolean
  cost_estimate: Record<string, unknown> | null
  result: { summary: string; created: CopilotEntityRef[]; updated: CopilotEntityRef[]; data?: Record<string, unknown> } | null
  error: string | null
  undoable: boolean
  created_at: string | null
  expires_at: string | null
}

export interface CopilotProposalCard {
  type: 'proposal'
  action: CopilotAction
}

export interface CopilotWizardCard {
  type: 'wizard'
  wizard: {
    kind: 'create_agent'
    name: string
    call_medium: 'voice' | 'chat'
    production_prompt?: string | null
    description?: string | null
  }
}

export type CopilotCard = CopilotDraftCard | CopilotProposalCard | CopilotWizardCard

export interface CopilotPageContext {
  route?: string
  entity_type?: string
  entity_id?: string
  title?: string
}

export type CopilotStreamEvent =
  | { event: 'turn_started'; data: { session_id: string; user_message_id: string; message_id: string; replayed?: boolean } }
  | { event: 'token'; data: { text: string } }
  | { event: 'tool_call'; data: { id: string; name: string } }
  | { event: 'tool_result'; data: { id: string; name: string; status: string; latency_ms: number } }
  | { event: 'draft'; data: CopilotDraftCard }
  | { event: 'proposal'; data: CopilotProposalCard }
  | { event: 'wizard'; data: CopilotWizardCard }
  | { event: 'error'; data: { code: string; message: string } }
  | { event: 'done'; data: { message_id: string; status: CopilotMessageStatus; replayed?: boolean } }

/**
 * Incremental Server-Sent Events parser. Feed it decoded text chunks as they
 * arrive; it returns every complete event and keeps partial ones buffered.
 * Comment lines (": keep-alive") are ignored.
 */
export class SseParser {
  private buffer = ''

  push(chunk: string): CopilotStreamEvent[] {
    this.buffer += chunk.replace(/\r\n/g, '\n')
    const events: CopilotStreamEvent[] = []
    let boundary = this.buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const block = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(boundary + 2)
      let event = ''
      const dataLines: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
      }
      if (event && dataLines.length) {
        try {
          events.push({ event, data: JSON.parse(dataLines.join('\n')) } as CopilotStreamEvent)
        } catch {
          // A malformed event is skipped rather than breaking the stream.
        }
      }
      boundary = this.buffer.indexOf('\n\n')
    }
    return events
  }
}

export class CopilotApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message)
  }
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const reasons = (detail as { reasons?: CopilotReason[] }).reasons
    if (reasons?.length) return reasons[0].message
  }
  return fallback
}

export class CopilotApi {
  constructor(
    private client: AxiosInstance,
    private streamHeaders: () => Record<string, string>,
  ) {}

  async status(): Promise<CopilotStatus> {
    return (await this.client.get('/api/v1/copilot/status')).data
  }

  async listSessions(cursor?: string): Promise<{ items: CopilotSession[]; next_cursor: string | null }> {
    return (await this.client.get('/api/v1/copilot/sessions', { params: { cursor, limit: 20 } })).data
  }

  async createSession(): Promise<CopilotSession> {
    return (await this.client.post('/api/v1/copilot/sessions', {})).data
  }

  async updateSession(id: string, data: { title?: string; status?: 'active' | 'archived' }): Promise<CopilotSession> {
    return (await this.client.patch(`/api/v1/copilot/sessions/${id}`, data)).data
  }

  async deleteSession(id: string): Promise<void> {
    await this.client.delete(`/api/v1/copilot/sessions/${id}`)
  }

  async listMessages(sessionId: string, beforeSeq?: number): Promise<{ items: CopilotMessage[]; has_more: boolean }> {
    return (
      await this.client.get(`/api/v1/copilot/sessions/${sessionId}/messages`, {
        params: { before_seq: beforeSeq, limit: 50 },
      })
    ).data
  }

  async listActions(sessionId: string): Promise<{ items: CopilotAction[] }> {
    return (await this.client.get(`/api/v1/copilot/sessions/${sessionId}/actions`)).data
  }

  async confirmAction(actionId: string, payload?: Record<string, unknown>): Promise<CopilotAction> {
    return (await this.client.post(`/api/v1/copilot/actions/${actionId}/confirm`, { payload })).data
  }

  async rejectAction(actionId: string): Promise<CopilotAction> {
    return (await this.client.post(`/api/v1/copilot/actions/${actionId}/reject`)).data
  }

  async undoAction(actionId: string): Promise<CopilotAction> {
    return (await this.client.post(`/api/v1/copilot/actions/${actionId}/undo`)).data
  }

  async cancel(sessionId: string, messageId: string): Promise<void> {
    await this.client.post(`/api/v1/copilot/sessions/${sessionId}/messages/${messageId}/cancel`)
  }

  /**
   * Send a message and stream the reply. axios can't stream POST bodies in the
   * browser, so this uses fetch with the same auth headers. On a 401 it makes
   * one axios call (which refreshes the session) and retries once.
   */
  async sendMessage(
    sessionId: string,
    body: { content: string; client_message_id: string; page_context?: CopilotPageContext; timezone?: string },
    onEvent: (event: CopilotStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const base = (this.client.defaults.baseURL || '').replace(/\/$/, '')
    const url = `${base}/api/v1/copilot/sessions/${sessionId}/messages`
    const send = () =>
      fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...this.streamHeaders() },
        body: JSON.stringify(body),
        signal,
      })

    let response = await send()
    if (response.status === 401) {
      await this.status().catch(() => undefined)
      response = await send()
    }
    if (!response.ok || !response.body) {
      let detail: unknown
      try {
        detail = (await response.json()).detail
      } catch {
        detail = undefined
      }
      throw new CopilotApiError(errorMessage(detail, `Request failed (${response.status})`), response.status, detail)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    const parser = new SseParser()
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event)
    }
    for (const event of parser.push(decoder.decode() + '\n\n')) onEvent(event)
  }
}
