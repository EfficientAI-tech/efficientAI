import { SANDBOX_CATALOG, cloneSeed, mainAgentConfig } from './catalog'
import {
  applyRememberedDismissals,
  issueSignature,
  loadDismissals,
  removeDismissal,
  saveDismissals,
  upsertDismissal,
} from './dismissals'
import { SEEDED_DISMISSALS, allFixtureSessions } from './fixtures'
import { DEFAULT_SEVERITY } from './labels'
import type {
  AgentConfig,
  AgentDismissal,
  Catalog,
  CreateManualChatInput,
  CreateSimulationInput,
  FlagMessageInput,
  HealthBadge,
  Issue,
  SendMessageInput,
  Session,
  SessionListItem,
} from './types'

const SESSIONS: Map<string, Session> = new Map()
let dismissals: AgentDismissal[] = []
let seeded = false

function useMock(): boolean {
  return import.meta.env.VITE_SANDBOX_MOCK !== '0'
}

function cloneSession(session: Session): Session {
  return JSON.parse(JSON.stringify(session)) as Session
}

function seedIfNeeded() {
  if (seeded) return
  seeded = true
  for (const session of allFixtureSessions()) {
    SESSIONS.set(session.id, session)
  }
  const stored = loadDismissals()
  dismissals = stored.length ? stored : [...SEEDED_DISMISSALS]
  if (!stored.length) saveDismissals(dismissals)
}

function applySessionDismissals(session: Session): Session {
  const next = cloneSession(session)
  const agentAId = next.agentA.platformAgentId
  next.issues = applyRememberedDismissals(next.issues, dismissals, agentAId)
  if (next.agentB?.platformAgentId) {
    const bIssues = applyRememberedDismissals(
      next.issues.filter((i) => i.agent === 'B'),
      dismissals,
      next.agentB.platformAgentId,
    )
    next.issues = next.issues.map((issue) => {
      if (issue.agent !== 'B') return issue
      return bIssues.find((i) => i.id === issue.id) ?? issue
    })
  }
  return next
}

function toListItem(session: Session): SessionListItem {
  const applied = applySessionDismissals(session)
  const open = applied.issues.filter((i) => i.status === 'open')
  return {
    id: applied.id,
    kind: applied.kind,
    status: applied.status,
    agentAName: applied.agentA.name,
    agentAModel: applied.agentA.llm.model,
    agentBName: applied.agentB?.name,
    agentBModel: applied.agentB?.llm.model,
    environmentName: applied.environment.name,
    openErrorCount: open.filter((i) => i.severity === 'error').length,
    openWarningCount: open.filter((i) => i.severity === 'warning').length,
    accuracy: applied.results?.accuracy,
    experience: applied.results?.experience,
    durationSeconds: applied.durationSeconds,
    createdAt: applied.createdAt,
  }
}

function newId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`
}

function envById(id: string) {
  const env = SANDBOX_CATALOG.environments.find((e) => e.id === id)
  if (!env) throw new Error('Environment not found')
  const seed = JSON.parse(JSON.stringify(env.seed)) as Record<string, unknown>
  return { ...env, seed, current: seed, final: seed }
}

export const sandboxApi = {
  isMock(): boolean {
    return useMock()
  },

  catalog(): Catalog {
    seedIfNeeded()
    return SANDBOX_CATALOG
  },

  listSessions(): SessionListItem[] {
    seedIfNeeded()
    return [...SESSIONS.values()]
      .map(toListItem)
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
  },

  getSession(id: string): Session | undefined {
    seedIfNeeded()
    const session = SESSIONS.get(id)
    return session ? applySessionDismissals(session) : undefined
  },

  healthForAgent(platformAgentId?: string): HealthBadge[] {
    seedIfNeeded()
    if (!platformAgentId) return []
    const sessions = [...SESSIONS.values()]
      .filter((s) => s.agentA.platformAgentId === platformAgentId)
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
    const latest = sessions[0]
    if (!latest) return []
    const applied = applySessionDismissals(latest)
    const counts = new Map<string, HealthBadge>()
    for (const issue of applied.issues.filter((i) => i.status === 'open' && i.configRef)) {
      const key = `${issue.configRef!.section}:${issue.configRef!.itemId ?? ''}`
      const existing = counts.get(key)
      if (existing) {
        existing.count += 1
        if (issue.severity === 'error') existing.severity = 'error'
      } else {
        counts.set(key, {
          section: issue.configRef!.section,
          itemId: issue.configRef!.itemId ?? '',
          severity: issue.severity,
          count: 1,
          label: `${issue.title} in last run`,
          issueId: issue.id,
          sessionId: applied.id,
        })
      }
    }
    return [...counts.values()]
  },

  createSimulation(input: CreateSimulationInput): Session {
    seedIfNeeded()
    const id = newId(input.asDraft ? 'draft' : 'sim')
    const session: Session = {
      id,
      kind: 'simulation',
      status: input.asDraft ? 'draft' : 'completed',
      createdAt: new Date().toISOString(),
      durationSeconds: input.asDraft ? undefined : 12,
      tokens: input.asDraft ? undefined : 420,
      environment: envById(input.environmentId),
      scenario: input.scenario,
      maxTurns: input.maxTurns,
      metricsSuiteId: input.metricsSuiteId,
      agentA: input.agentA,
      agentB: input.agentB,
      turns: input.asDraft
        ? []
        : [
            {
              idx: 0,
              speaker: 'B',
              text: input.scenario || 'Hello, can you help me fetch an entry?',
              ts: new Date().toISOString(),
            },
            {
              idx: 1,
              speaker: 'A',
              text: 'I can help with that. Let me look it up.',
              ts: new Date().toISOString(),
              eventIds: [`${id}-tool`],
            },
          ],
      events: input.asDraft
        ? []
        : [
            {
              id: `${id}-tool`,
              ts: new Date().toISOString(),
              agent: 'A',
              type: 'tool',
              name: 'get_entry',
              status: 'ok',
              turnIdx: 1,
              durationMs: 40,
              input: { entry_id: 'ENT-1001' },
              output: { id: 'ENT-1001' },
            },
          ],
      issues: [],
      reliability: [],
      eventsChecked: { tool: input.asDraft ? 0 : 1, skill: 0, api: 0, rag: 0 },
      traces: { A: [], B: [] },
      results: input.asDraft
        ? undefined
        : {
            accuracy: 0.8,
            experience: 0.75,
            metrics: [
              {
                name: 'Task completion',
                score: 1,
                passed: true,
                kind: 'deterministic',
                axis: 'accuracy',
              },
            ],
            outcome: {
              dbMatch: true,
              dbDiff: { added: [], changed: [], removed: [] },
              communicateChecks: [],
            },
          },
    }
    SESSIONS.set(id, session)
    return applySessionDismissals(session)
  },

  createManualChat(input: CreateManualChatInput): Session {
    seedIfNeeded()
    const id = newId('chat')
    const agent = input.agent
    const session: Session = {
      id,
      kind: 'manual',
      status: 'active',
      createdAt: new Date().toISOString(),
      environment: envById(input.environmentId),
      agentA: input.target === 'A' ? agent : mainAgentConfig({ name: 'Main agent (unused)' }),
      agentB: input.target === 'B' ? agent : undefined,
      chatTarget: input.target,
      turns: [],
      events: [],
      issues: [],
      reliability: [],
      eventsChecked: { tool: 0, skill: 0, api: 0, rag: 0 },
      traces: { A: [] },
      configHistory: [],
    }
    if (input.target === 'B') {
      session.agentA = mainAgentConfig()
      session.agentB = agent
    }
    SESSIONS.set(id, session)
    return applySessionDismissals(session)
  },

  forkSession(sessionId: string, turnIdx: number): Session {
    seedIfNeeded()
    const source = SESSIONS.get(sessionId)
    if (!source) throw new Error('Session not found')
    const id = newId('chat')
    const forked: Session = {
      ...cloneSession(source),
      id,
      kind: 'manual',
      status: 'active',
      createdAt: new Date().toISOString(),
      chatTarget: 'A',
      forkedFrom: { sessionId, turnIdx },
      agentB: undefined,
      results: undefined,
      turns: [
        ...source.turns.filter((t) => t.idx <= turnIdx),
        {
          idx: turnIdx + 1,
          speaker: 'A',
          text: '',
          ts: new Date().toISOString(),
          divider: 'branch',
          dividerSummary: `Forked from ${sessionId} at turn ${turnIdx}`,
        },
      ],
    }
    SESSIONS.set(id, forked)
    return applySessionDismissals(forked)
  },

  sendMessage(input: SendMessageInput): Session {
    seedIfNeeded()
    const session = SESSIONS.get(input.sessionId)
    if (!session) throw new Error('Session not found')
    const fail = /fail|500|broken/i.test(input.text)
    const fetch = /fetch|get_entry|ENT-/i.test(input.text)
    const nextIdx = session.turns.filter((t) => !t.divider).length
      ? Math.max(...session.turns.map((t) => t.idx)) + 1
      : 0
    const now = new Date().toISOString()
    const human: Session['turns'][number] = {
      idx: nextIdx,
      speaker: 'human',
      text: input.text,
      ts: now,
    }
    const eventId = `${session.id}-e-${nextIdx + 1}`
    const agentTurnIdx = nextIdx + 1
    if (fail) {
      session.events.push({
        id: eventId,
        ts: now,
        agent: 'A',
        type: 'api',
        name: 'orders_lookup',
        status: 'error',
        turnIdx: agentTurnIdx,
        durationMs: 420,
        api: { method: 'GET', host: 'orders-api', statusCode: 500, retries: 1 },
        error: { message: '500 from external API' },
      })
      session.issues.push({
        id: newId('iss'),
        severity: DEFAULT_SEVERITY.external_api_failure,
        category: 'external_api_failure',
        source: 'rule',
        agent: 'A',
        title: 'orders-api returned 500',
        whatHappened: 'Tool `orders_lookup` failed: 500 from external API.',
        whatToCheck: 'Verify the credential for `orders-api`.',
        turnIdx: agentTurnIdx,
        eventIds: [eventId],
        configRef: { agent: 'A', section: 'tools', itemId: 'orders-api' },
        status: 'open',
      })
      session.turns.push(human, {
        idx: agentTurnIdx,
        speaker: 'A',
        text: 'The orders service failed. I can still work from the local records DB.',
        ts: now,
        eventIds: [eventId],
      })
    } else if (fetch) {
      session.events.push({
        id: eventId,
        ts: now,
        agent: 'A',
        type: 'tool',
        name: 'get_entry',
        status: 'ok',
        turnIdx: agentTurnIdx,
        durationMs: 48,
        input: { entry_id: 'ENT-1001' },
        output: { id: 'ENT-1001', customer: 'Priya Shah' },
      })
      session.turns.push(human, {
        idx: agentTurnIdx,
        speaker: 'A',
        text: 'ENT-1001 belongs to Priya Shah and is currently open.',
        ts: now,
        eventIds: [eventId],
      })
    } else {
      session.turns.push(human, {
        idx: agentTurnIdx,
        speaker: 'A',
        text: 'Got it. Tell me if you want me to fetch or record an entry.',
        ts: now,
      })
    }
    session.status = 'active'
    session.durationSeconds = (session.durationSeconds ?? 0) + 4
    SESSIONS.set(session.id, session)
    return applySessionDismissals(session)
  },

  stopSession(id: string): Session {
    seedIfNeeded()
    const session = SESSIONS.get(id)
    if (!session) throw new Error('Session not found')
    session.status = session.kind === 'manual' ? 'ended' : 'stopped'
    session.endedAt = new Date().toISOString()
    return applySessionDismissals(session)
  },

  deleteSession(id: string): void {
    seedIfNeeded()
    SESSIONS.delete(id)
  },

  duplicateSession(id: string): Session {
    seedIfNeeded()
    const source = SESSIONS.get(id)
    if (!source) throw new Error('Session not found')
    if (source.kind === 'manual') {
      return this.createManualChat({
        environmentId: source.environment.id,
        agent: source.chatTarget === 'B' && source.agentB ? source.agentB : source.agentA,
        target: source.chatTarget ?? 'A',
      })
    }
    return this.createSimulation({
      environmentId: source.environment.id,
      scenario: source.scenario ?? '',
      maxTurns: source.maxTurns ?? 8,
      metricsSuiteId: source.metricsSuiteId,
      agentA: source.agentA,
      agentB: source.agentB ?? mainAgentConfig({ name: 'Test agent' }),
      asDraft: true,
    })
  },

  resetEnvironment(id: string): Session {
    seedIfNeeded()
    const session = SESSIONS.get(id)
    if (!session) throw new Error('Session not found')
    const seed = cloneSeed()
    session.environment = { ...session.environment, current: seed, final: seed, seed }
    const idx = Math.max(-1, ...session.turns.map((t) => t.idx)) + 1
    session.turns.push({
      idx,
      speaker: 'A',
      text: '',
      ts: new Date().toISOString(),
      divider: 'env_reset',
      dividerSummary: 'Environment reset to seed data',
    })
    session.configHistory = [
      ...(session.configHistory ?? []),
      { ts: new Date().toISOString(), summary: 'Environment reset' },
    ]
    return applySessionDismissals(session)
  },

  updateConfig(id: string, agent: AgentConfig, summary: string): Session {
    seedIfNeeded()
    const session = SESSIONS.get(id)
    if (!session) throw new Error('Session not found')
    if (session.chatTarget === 'B' && session.agentB) session.agentB = agent
    else session.agentA = agent
    const idx = Math.max(-1, ...session.turns.map((t) => t.idx)) + 1
    session.turns.push({
      idx,
      speaker: 'A',
      text: '',
      ts: new Date().toISOString(),
      divider: 'config_changed',
      dividerSummary: summary,
    })
    session.configHistory = [...(session.configHistory ?? []), { ts: new Date().toISOString(), summary }]
    return applySessionDismissals(session)
  },

  flagMessage(input: FlagMessageInput): Session {
    seedIfNeeded()
    const session = SESSIONS.get(input.sessionId)
    if (!session) throw new Error('Session not found')
    const turn = session.turns.find((t) => t.idx === input.turnIdx)
    if (turn) turn.flaggedByUser = true
    session.issues.push({
      id: newId('iss'),
      severity: DEFAULT_SEVERITY.user_flagged,
      category: 'user_flagged',
      source: 'user',
      agent: 'A',
      title: 'Reply flagged as wrong',
      whatHappened: input.note || 'You marked this agent reply as wrong.',
      whatToCheck: 'Review the prompt and the tools used on this turn.',
      turnIdx: input.turnIdx,
      eventIds: turn?.eventIds ?? [],
      configRef: { agent: 'A', section: 'prompt' },
      status: 'open',
    })
    return applySessionDismissals(session)
  },

  dismissIssue(sessionId: string, issueId: string, reason?: string): Session {
    seedIfNeeded()
    const session = SESSIONS.get(sessionId)
    if (!session) throw new Error('Session not found')
    const issue = session.issues.find((i) => i.id === issueId)
    if (!issue) throw new Error('Issue not found')
    const now = new Date().toISOString()
    issue.status = 'dismissed'
    issue.dismissReason = reason
    issue.dismissedAt = now
    const agentId =
      issue.agent === 'B' ? session.agentB?.platformAgentId : session.agentA.platformAgentId
    if (agentId) {
      dismissals = upsertDismissal(dismissals, {
        agentId,
        signature: issueSignature(issue),
        reason,
        dismissedAt: now,
        sourceSessionId: sessionId,
      })
      saveDismissals(dismissals)
    }
    return applySessionDismissals(session)
  },

  restoreIssue(sessionId: string, issueId: string): Session {
    seedIfNeeded()
    const session = SESSIONS.get(sessionId)
    if (!session) throw new Error('Session not found')
    const issue = session.issues.find((i) => i.id === issueId)
    if (!issue) throw new Error('Issue not found')
    issue.status = 'open'
    issue.dismissReason = undefined
    issue.dismissedAt = undefined
    issue.rememberedFromSessionId = undefined
    const agentId =
      issue.agent === 'B' ? session.agentB?.platformAgentId : session.agentA.platformAgentId
    dismissals = removeDismissal(dismissals, issueSignature(issue), agentId)
    saveDismissals(dismissals)
    return applySessionDismissals(session)
  },

  runMetrics(sessionId: string): Session {
    seedIfNeeded()
    const session = SESSIONS.get(sessionId)
    if (!session) throw new Error('Session not found')
    session.status = session.kind === 'manual' ? 'idle' : 'completed'
    session.results = {
      accuracy: 0.76,
      experience: 0.71,
      metrics: [
        {
          name: 'Task completion',
          score: 0.8,
          passed: true,
          kind: 'deterministic',
          axis: 'accuracy',
          rationale: 'Scored from the current transcript and DB state.',
        },
        {
          name: 'Conciseness',
          score: 0.71,
          passed: true,
          kind: 'llm_judge',
          axis: 'experience',
        },
      ],
      outcome: {
        dbMatch: true,
        dbDiff: session.results?.outcome.dbDiff ?? { added: [], changed: [], removed: [] },
        communicateChecks: [{ text: 'Agent responded to the user', passed: true }],
      },
    }
    return applySessionDismissals(session)
  },

  emptyAgentConfig(role: 'A' | 'B'): AgentConfig {
    return role === 'A'
      ? {
          name: '',
          prompt: '',
          llm: { provider: 'openai', model: 'gpt-4.1' },
          framework: 'native',
          tools: [],
          skills: [],
          harness: SANDBOX_CATALOG.harnesses[0],
          rag: [],
        }
      : {
          name: '',
          prompt: '',
          llm: { provider: 'anthropic', model: 'claude-sonnet-4' },
          framework: 'native',
          tools: [],
          skills: [],
          harness: SANDBOX_CATALOG.harnesses[0],
          rag: [],
        }
  },
}

export function openIssueCounts(issues: Issue[]): { error: number; warning: number; info: number } {
  const open = issues.filter((i) => i.status === 'open')
  return {
    error: open.filter((i) => i.severity === 'error').length,
    warning: open.filter((i) => i.severity === 'warning').length,
    info: open.filter((i) => i.severity === 'info').length,
  }
}
