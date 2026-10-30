import type { DashboardSource } from './timeBuckets'
import {
  computeCallMetrics,
  type CallLike,
  type CallTurn,
  type PerCallMetrics,
} from './callMetrics'
import {
  MOCK_AGENTS,
  MOCK_METRICS,
  MOCK_TOOLS,
  USE_CASE_INTEGRATION,
  SCENARIO_INTENT,
  clamp,
  hashString,
  metricsForAgent,
  mulberry32,
  primaryValueAt,
  scenarioAdjustment,
  scenariosForAgent,
} from './mockCatalog'
import { buildCallUsage, type CallUsage } from './mockUsage'

export interface MockCallScore {
  value: number | string | boolean
  type: string
  metric_name: string
  failed: boolean
  evidenceTurnIndexes: number[]
  rationale?: string
}

export interface MockCall extends CallLike {
  agentName: string
  scenarioId?: string
  scenarioName?: string
  metric_scores: Record<string, MockCallScore>
  computed: PerCallMetrics
  usage: CallUsage
}

const CORPUS_DAYS = 200
const LIVE_MULTIPLIER = 3

interface AgentGlobalProfile {
  duration: number
  silence: number
  silenceBreakDaysAgo?: number
  silenceBreakDelta?: number
  earlyRate: number
  toolFailRate: number
  ragFailRate: number
  talkRatio: number
  closing: number
  closingBreakDaysAgo?: number
  closingBreakDelta?: number
}

const GLOBAL_PROFILE: Record<string, AgentGlobalProfile> = {
  'mock-agent-support-eu': {
    duration: 145,
    silence: 1.15,
    silenceBreakDaysAgo: 4,
    silenceBreakDelta: 1.35,
    earlyRate: 0.16,
    toolFailRate: 0.2,
    ragFailRate: 0.07,
    talkRatio: 1.25,
    closing: 3.6,
    closingBreakDaysAgo: 4,
    closingBreakDelta: -0.8,
  },
  'mock-agent-sales-outbound': {
    duration: 175,
    silence: 0.85,
    earlyRate: 0.06,
    toolFailRate: 0.05,
    ragFailRate: 0.04,
    talkRatio: 0.95,
    closing: 4.2,
  },
  'mock-agent-billing': {
    duration: 95,
    silence: 1.7,
    earlyRate: 0.12,
    toolFailRate: 0.08,
    ragFailRate: 0.3,
    talkRatio: 2.15,
    closing: 3.5,
  },
}

const LINES: Record<'human' | 'agent', string[]> = {
  human: [
    'I already explained this to the last person.',
    'Can you just process the refund?',
    'The delivery never arrived.',
    'Hold on, I need to find my account number.',
    'That is not what I asked.',
    'Fine, what is the next step then?',
    'I want to cancel after this billing cycle.',
    'Are you still there?',
  ],
  agent: [
    'I understand this has been frustrating.',
    'Per our policy the refund window is fourteen days.',
    'Let me look that up for you.',
    'Could you confirm the last four digits of the card?',
    'I can schedule a callback if that is easier.',
    'I do not have that in the knowledge base.',
    'Is there anything else I can help with today?',
    'I am transferring you to billing now.',
  ],
}

function profileAt(agentId: string, daysAgo: number, rng: () => number): AgentGlobalProfile {
  const base = GLOBAL_PROFILE[agentId] ?? GLOBAL_PROFILE['mock-agent-support-eu']
  const silence =
    base.silenceBreakDaysAgo != null &&
    base.silenceBreakDelta != null &&
    daysAgo <= base.silenceBreakDaysAgo
      ? base.silence + base.silenceBreakDelta
      : base.silence
  const closing =
    base.closingBreakDaysAgo != null &&
    base.closingBreakDelta != null &&
    daysAgo <= base.closingBreakDaysAgo
      ? base.closing + base.closingBreakDelta
      : base.closing
  return {
    ...base,
    silence: clamp(silence + (rng() - 0.5) * 0.2, 0.3, 6),
    closing: clamp(closing + (rng() - 0.5) * 0.3, 1, 5),
    duration: clamp(base.duration + (rng() - 0.5) * 40, 18, 480),
    talkRatio: clamp(base.talkRatio + (rng() - 0.5) * 0.15, 0.3, 3.5),
  }
}

function pickTools(
  rng: () => number,
  profile: AgentGlobalProfile,
): Array<{ name: string; failed: boolean; integration: string }> {
  if (rng() < 0.2) return []
  const count = 1 + Math.floor(rng() * 3)
  const used = new Set<string>()
  const tools: Array<{ name: string; failed: boolean; integration: string }> = []
  for (let i = 0; i < count; i += 1) {
    const name = MOCK_TOOLS[Math.floor(rng() * MOCK_TOOLS.length)]
    if (used.has(name)) continue
    used.add(name)
    const fallback = USE_CASE_INTEGRATION[name]
    const integration = rng() < 0.18 ? (rng() < 0.5 ? 'notion' : 'slack') : fallback
    tools.push({
      name,
      integration,
      failed: rng() < clamp(profile.toolFailRate * 1.8, 0.04, 0.55),
    })
  }
  return tools
}

function buildTurns(
  rng: () => number,
  profile: AgentGlobalProfile,
  endedEarly: boolean,
  scenarioName: string | undefined,
  tools: Array<{ name: string; failed: boolean; integration: string }>,
): CallTurn[] {
  const humanTurns = 3 + Math.floor(rng() * 3)
  const agentTurns = Math.max(2, Math.round(humanTurns * profile.talkRatio))
  const total = humanTurns + agentTurns
  const turns: CallTurn[] = []
  let t = rng() * 1.5
  let next: 'human' | 'agent' = rng() < 0.7 ? 'human' : 'agent'
  let remainingHuman = humanTurns
  let remainingAgent = agentTurns
  let toolIndex = 0
  for (let i = 0; i < total; i += 1) {
    if (remainingHuman === 0) next = 'agent'
    if (remainingAgent === 0) next = 'human'
    const speaker = next
    if (speaker === 'human') remainingHuman -= 1
    else remainingAgent -= 1
    const duration = 1.2 + rng() * 4.5
    const textPool = LINES[speaker]
    let text = textPool[Math.floor(rng() * textPool.length)]
    if (i === 0 && scenarioName) text = `${scenarioName}. ${text}`
    const turn: CallTurn = {
      speaker,
      text,
      start: Number(t.toFixed(2)),
      end: Number((t + duration).toFixed(2)),
    }
    if (speaker === 'agent' && toolIndex < tools.length) {
      turn.toolCall = tools[toolIndex]
      toolIndex += 1
    }
    if (speaker === 'agent' && rng() < profile.ragFailRate) {
      turn.ragCall = { query: 'policy lookup', failed: rng() < 0.7 }
    }
    turns.push(turn)
    t += duration + clamp(profile.silence + (rng() - 0.4) * profile.silence, 0.15, 12)
    next = speaker === 'human' ? 'agent' : 'human'
  }
  if (endedEarly && turns.length > 2) {
    const last = turns[turns.length - 1]
    last.text = `${last.text} …`
  }
  return turns
}

function scoreLocalMetrics(
  agentId: string,
  daysAgo: number,
  rng: () => number,
  scenarioId: string | undefined,
  turns: CallTurn[],
  callIndex: number,
): Record<string, MockCallScore> {
  const scores: Record<string, MockCallScore> = {}
  const agentTurns = turns
    .map((turn, index) => (turn.speaker === 'agent' ? index : -1))
    .filter((index) => index >= 0)
  const pickEvidence = (failed: boolean): number[] => {
    if (!failed || agentTurns.length === 0) return []
    const first = agentTurns[Math.floor(rng() * agentTurns.length)]
    const extra = agentTurns[Math.floor(rng() * agentTurns.length)]
    return extra === first ? [first] : [first, extra]
  }

  const allowed = new Set(metricsForAgent(agentId))
  for (const metric of MOCK_METRICS) {
    if (!allowed.has(metric.id)) continue
    if (agentId === 'mock-agent-billing' && metric.id === 'mock-metric-accuracy' && callIndex % 5 !== 0) {
      continue
    }
    const centre = clamp(
      primaryValueAt(agentId, metric.id, daysAgo, rng) + scenarioAdjustment(scenarioId, metric.id),
      0.02,
      0.99,
    )
    if (metric.kind === 'rating' || metric.kind === 'number') {
      const value = Number(clamp(centre + (rng() - 0.5) * 0.35, 0, 1).toFixed(2))
      const failed = value < 0.55
      scores[metric.id] = {
        value,
        type: metric.kind,
        metric_name: metric.name,
        failed,
        evidenceTurnIndexes: pickEvidence(failed),
        rationale: failed
          ? `The agent scored ${value} on ${metric.name} — the highlighted turns skip acknowledgement.`
          : undefined,
      }
    } else if (metric.kind === 'boolean') {
      const value = rng() < centre
      const failed = !value
      scores[metric.id] = {
        value,
        type: 'boolean',
        metric_name: metric.name,
        failed,
        evidenceTurnIndexes: pickEvidence(failed),
        rationale: failed ? `${metric.name} failed on this call.` : undefined,
      }
    } else {
      const labels = metric.labels ?? []
      let value: string
      if (metric.id === 'mock-metric-outcome') {
        value = rng() < centre ? 'angry_hangup' : labels[Math.floor(rng() * Math.max(1, labels.length - 1))]
      } else {
        value = labels[Math.floor(rng() * labels.length)] ?? 'unknown'
      }
      const failed = metric.policy?.failure_values?.includes(value) ?? false
      scores[metric.id] = {
        value,
        type: 'category',
        metric_name: metric.name,
        failed,
        evidenceTurnIndexes: pickEvidence(failed),
        rationale: failed ? `Outcome labelled ${value}.` : undefined,
      }
    }
  }
  return scores
}

function liveIntentScore(rng: () => number, scenarioId: string | undefined): Record<string, MockCallScore> {
  const labels = MOCK_METRICS.find((metric) => metric.id === 'mock-metric-intent')?.labels ?? []
  const mapped = scenarioId ? SCENARIO_INTENT[scenarioId] : undefined
  const value = mapped && rng() < 0.7 ? mapped : (labels[Math.floor(rng() * labels.length)] ?? 'billing_question')
  return {
    'mock-metric-intent': {
      value,
      type: 'category',
      metric_name: 'Customer Intent',
      failed: false,
      evidenceTurnIndexes: [],
    },
  }
}

function generateCorpus(now: number): MockCall[] {
  const calls: MockCall[] = []
  for (const agent of MOCK_AGENTS) {
    for (let daysAgo = 0; daysAgo < CORPUS_DAYS; daysAgo += 1) {
      const dayStart = new Date(now - daysAgo * 86400000)
      dayStart.setHours(8, 0, 0, 0)
      for (const source of ['simulation', 'live'] as DashboardSource[]) {
        const count =
          source === 'simulation'
            ? agent.runsPerDay
            : Math.max(2, Math.round(agent.runsPerDay * LIVE_MULTIPLIER))
        for (let i = 0; i < count; i += 1) {
          const rng = mulberry32(hashString(`${agent.id}|${source}|${daysAgo}|${i}`))
          const started = new Date(dayStart.getTime() + (i * 3600000) / Math.max(1, count) + rng() * 400000)
          const profile = profileAt(agent.id, daysAgo + rng() * 0.4, rng)
          const endedEarly = rng() < profile.earlyRate
          const agentScenarios = scenariosForAgent(agent.id)
          const scenario = agentScenarios[Math.floor(rng() * Math.max(1, agentScenarios.length))]
          const tools = pickTools(rng, profile)
          const turns = buildTurns(rng, profile, endedEarly, scenario?.name, tools)
          const lastEnd = turns[turns.length - 1]?.end ?? profile.duration
          const durationSeconds = Math.max(12, Math.round(endedEarly ? lastEnd : profile.duration))
          const closingQuality = Number(
            clamp(endedEarly ? profile.closing - 1.1 : profile.closing, 1, 5).toFixed(1),
          )
          const endedReason = endedEarly
            ? rng() < 0.5
              ? 'silence_timeout'
              : 'caller_hangup'
            : 'completed'
          const base: CallLike = {
            id: `mock-call-${source}-${agent.id}-${daysAgo}-${i}`,
            agentId: agent.id,
            source,
            startedAt: started.toISOString(),
            durationSeconds,
            turns,
            endedReason,
            endedEarly,
            closingQuality,
          }
          calls.push({
            ...base,
            agentName: agent.name,
            scenarioId: scenario?.id,
            scenarioName: scenario?.name,
            metric_scores:
              source === 'simulation'
                ? scoreLocalMetrics(agent.id, daysAgo, rng, scenario?.id, turns, i)
                : liveIntentScore(rng, scenario?.id),
            computed: computeCallMetrics(base),
            usage: buildCallUsage({
              agentId: agent.id,
              durationSeconds,
              startedAt: started.toISOString(),
              rng,
            }),
          })
        }
      }
    }
  }
  return calls
}

let cached: { now: number; calls: MockCall[] } | null = null

export function getMockCorpus(now = Date.now()): MockCall[] {
  if (cached && Math.abs(now - cached.now) < 60_000) return cached.calls
  cached = { now, calls: generateCorpus(now) }
  return cached.calls
}

export function listMockCalls(params: {
  agentId?: string | null
  source?: DashboardSource
  since?: string
  until?: string
  now?: number
}): MockCall[] {
  const sinceMs = params.since ? new Date(params.since).getTime() : 0
  const untilMs = params.until ? new Date(params.until).getTime() : Number.POSITIVE_INFINITY
  return getMockCorpus(params.now).filter((call) => {
    if (params.agentId && call.agentId !== params.agentId) return false
    if (params.source && call.source !== params.source) return false
    const ts = new Date(call.startedAt).getTime()
    return ts >= sinceMs && ts <= untilMs
  })
}

export function getMockCall(id: string, now = Date.now()): MockCall | undefined {
  return getMockCorpus(now).find((call) => call.id === id)
}
