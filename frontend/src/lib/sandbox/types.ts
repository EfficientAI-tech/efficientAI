export type AgentRole = 'A' | 'B'
export type Speaker = AgentRole | 'human'
export type SessionKind = 'simulation' | 'manual'
export type FrameworkId = 'native' | 'livekit' | 'pipecat'
export type ToolAccess = 'read' | 'write'
export type ToolKind = 'environment' | 'http' | 'mcp'
export type EventType = 'llm' | 'tool' | 'skill' | 'api' | 'rag' | 'db' | 'harness' | 'message'
export type EventStatus = 'ok' | 'error' | 'timeout'
export type IssueSeverity = 'error' | 'warning' | 'info'
export type IssueSource = 'rule' | 'llm_judge' | 'user'
export type IssueStatus = 'open' | 'dismissed'
export type ConfigSection = 'tools' | 'skills' | 'harness' | 'rag' | 'llm' | 'prompt'

export type IssueCategory =
  | 'tool_failed'
  | 'invalid_tool_args'
  | 'wrong_tool'
  | 'skill_misuse'
  | 'external_api_failure'
  | 'retrieval_problem'
  | 'harness_llm_error'
  | 'policy_violation'
  | 'expected_action_missing'
  | 'user_flagged'

export type SimulationStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'evaluating'
  | 'completed'
  | 'failed'
  | 'stopped'

export type ManualStatus = 'active' | 'idle' | 'ended' | 'failed'

export type SessionStatus = SimulationStatus | ManualStatus

export type LlmConfig = {
  provider: string
  model: string
  credentialId?: string
  temperature?: number
  maxTokens?: number
}

export type ToolDef = {
  id: string
  name: string
  description: string
  access: ToolAccess
  kind: ToolKind
  schema: Record<string, unknown>
}

export type SkillDef = {
  id: string
  name: string
  markdown: string
}

export type RagAttachment = {
  collectionId: string
  name: string
  docCount: number
  topK: number
  threshold?: number
}

export type HarnessConfig = {
  id: string
  name: string
  settings: Record<string, string>
}

export type AgentConfig = {
  name: string
  platformAgentId?: string
  prompt: string
  llm: LlmConfig
  voice?: { stt?: string; tts?: string }
  framework: FrameworkId
  tools: ToolDef[]
  skills: SkillDef[]
  harness?: HarnessConfig
  rag: RagAttachment[]
}

export type ActivityEvent = {
  id: string
  ts: string
  agent: AgentRole
  type: EventType
  name: string
  status: EventStatus
  durationMs?: number
  turnIdx?: number
  spanId?: string
  input?: unknown
  output?: unknown
  error?: { message: string; code?: string }
  api?: { method: string; host: string; statusCode?: number; retries?: number }
}

export type Issue = {
  id: string
  severity: IssueSeverity
  category: IssueCategory
  source: IssueSource
  agent: AgentRole
  title: string
  whatHappened: string
  whatToCheck: string
  turnIdx?: number
  eventIds: string[]
  configRef?: { agent: AgentRole; section: ConfigSection; itemId?: string }
  status: IssueStatus
  dismissReason?: string
  dismissedAt?: string
  rememberedFromSessionId?: string
}

export type AgentDismissal = {
  agentId?: string
  signature: string
  reason?: string
  dismissedAt: string
  sourceSessionId: string
}

export type ReliabilityRow = {
  kind: 'tool' | 'skill' | 'api'
  name: string
  calls: number
  failures: number
  avgLatencyMs?: number
  topError?: string
}

export type MetricResult = {
  name: string
  score: number
  passed?: boolean
  kind: 'deterministic' | 'llm_judge'
  rationale?: string
  axis: 'accuracy' | 'experience'
}

export type DbDiff = {
  added: Record<string, unknown>[]
  changed: { path: string; before: unknown; after: unknown }[]
  removed: Record<string, unknown>[]
}

export type SessionResults = {
  accuracy: number
  experience: number
  metrics: MetricResult[]
  outcome: {
    dbMatch: boolean
    dbDiff: DbDiff
    communicateChecks: { text: string; passed: boolean }[]
  }
}

export type Span = {
  id: string
  parentId?: string
  name: string
  type: EventType
  agent: AgentRole
  startMs: number
  durationMs: number
  status: EventStatus
  issueId?: string
  eventId?: string
  attributes?: Record<string, unknown>
}

export type TurnDivider = 'env_reset' | 'config_changed' | 'branch'

export type Turn = {
  idx: number
  speaker: Speaker
  text: string
  branchId?: string
  flaggedByUser?: boolean
  ts: string
  eventIds?: string[]
  divider?: TurnDivider
  dividerSummary?: string
}

export type SandboxEnvironment = {
  id: string
  name: string
  domain: string
  description: string
  policy: string
  seed: Record<string, unknown>
  current?: Record<string, unknown>
  final?: Record<string, unknown>
  toolIds: string[]
}

export type Session = {
  id: string
  kind: SessionKind
  status: SessionStatus
  createdAt: string
  endedAt?: string
  durationSeconds?: number
  tokens?: number
  costUsd?: number
  environment: SandboxEnvironment
  scenario?: string
  maxTurns?: number
  metricsSuiteId?: string
  agentA: AgentConfig
  agentB?: AgentConfig
  chatTarget?: AgentRole
  forkedFrom?: { sessionId: string; turnIdx: number }
  configHistory?: { ts: string; summary: string }[]
  turns: Turn[]
  events: ActivityEvent[]
  issues: Issue[]
  reliability: ReliabilityRow[]
  eventsChecked: { tool: number; skill: number; api: number; rag: number }
  results?: SessionResults
  traces: { A: Span[]; B?: Span[] }
  activeBranchId?: string
}

export type SessionListItem = {
  id: string
  kind: SessionKind
  status: SessionStatus
  agentAName: string
  agentAModel: string
  agentBName?: string
  agentBModel?: string
  environmentName: string
  openErrorCount: number
  openWarningCount: number
  accuracy?: number
  experience?: number
  durationSeconds?: number
  createdAt: string
}

export type Catalog = {
  environments: SandboxEnvironment[]
  tools: ToolDef[]
  skills: SkillDef[]
  harnesses: HarnessConfig[]
  ragCollections: RagAttachment[]
  metricsSuites: { id: string; name: string; description: string }[]
  platformAgents: { id: string; name: string; role: AgentRole; config: AgentConfig }[]
  llmOptions: { provider: string; models: string[] }[]
}

export type HealthBadge = {
  section: ConfigSection
  itemId: string
  severity: IssueSeverity
  count: number
  label: string
  issueId?: string
  sessionId?: string
}

export type CreateSimulationInput = {
  environmentId: string
  scenario: string
  maxTurns: number
  metricsSuiteId?: string
  agentA: AgentConfig
  agentB: AgentConfig
  asDraft?: boolean
}

export type CreateManualChatInput = {
  environmentId: string
  agent: AgentConfig
  target: AgentRole
}

export type SendMessageInput = {
  sessionId: string
  text: string
}

export type FlagMessageInput = {
  sessionId: string
  turnIdx: number
  note?: string
}
