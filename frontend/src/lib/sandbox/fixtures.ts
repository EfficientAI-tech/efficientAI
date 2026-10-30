import { cloneSeed, mainAgentConfig, RECORDS_ENV, testAgentConfig } from './catalog'
import type {
  ActivityEvent,
  AgentDismissal,
  Issue,
  Session,
  SessionResults,
  Span,
  Turn,
} from './types'

const ISO = (offsetMinutes: number) =>
  new Date(Date.now() - offsetMinutes * 60_000).toISOString()

function envSnapshot(
  extra?: Partial<typeof RECORDS_ENV> & {
    current?: Record<string, unknown>
    final?: Record<string, unknown>
  },
) {
  return { ...RECORDS_ENV, ...extra }
}

function spanFromEvent(event: ActivityEvent, startMs: number): Span {
  return {
    id: event.spanId || `span-${event.id}`,
    name: event.name,
    type: event.type,
    agent: event.agent,
    startMs,
    durationMs: event.durationMs ?? 40,
    status: event.status,
    eventId: event.id,
    attributes: {
      input: event.input,
      output: event.output,
      error: event.error,
      api: event.api,
    },
  }
}

function tracesFor(events: ActivityEvent[]): Session['traces'] {
  const A: Span[] = []
  const B: Span[] = []
  let t = 0
  for (const event of events) {
    const span = spanFromEvent(event, t)
    if (event.agent === 'A') A.push(span)
    else B.push(span)
    t += (event.durationMs ?? 40) + 12
  }
  return { A, B }
}

const SUCCESS_RESULTS: SessionResults = {
  accuracy: 0.92,
  experience: 0.81,
  metrics: [
    {
      name: 'Task completion',
      score: 1,
      passed: true,
      kind: 'deterministic',
      axis: 'accuracy',
      rationale: 'Final DB contains the recorded feedback note.',
    },
    {
      name: 'Faithfulness',
      score: 0.9,
      passed: true,
      kind: 'llm_judge',
      axis: 'accuracy',
      rationale: 'Agent restated the fetched entry without inventing fields.',
    },
    {
      name: 'Conversation progression',
      score: 0.84,
      passed: true,
      kind: 'llm_judge',
      axis: 'experience',
      rationale: 'Each turn advanced the fetch-then-record goal.',
    },
    {
      name: 'Conciseness',
      score: 0.78,
      passed: true,
      kind: 'llm_judge',
      axis: 'experience',
      rationale: 'Replies stayed short and on-task.',
    },
  ],
  outcome: {
    dbMatch: true,
    dbDiff: {
      added: [],
      changed: [
        {
          path: 'entries[0].notes',
          before: 'Asked about order delay',
          after: 'Asked about order delay. Customer confirmed the delay was resolved.',
        },
      ],
      removed: [],
    },
    communicateChecks: [
      { text: 'Told the customer the entry was fetched', passed: true },
      { text: 'Confirmed that feedback was recorded', passed: true },
    ],
  },
}

function successEvents(): ActivityEvent[] {
  return [
    {
      id: 'e-s-1',
      ts: ISO(120),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 0,
      durationMs: 20,
    },
    {
      id: 'e-s-2',
      ts: ISO(119),
      agent: 'A',
      type: 'llm',
      name: 'gpt-4.1',
      status: 'ok',
      turnIdx: 1,
      durationMs: 420,
      spanId: 'span-s-llm-1',
    },
    {
      id: 'e-s-3',
      ts: ISO(118),
      agent: 'A',
      type: 'tool',
      name: 'get_entry',
      status: 'ok',
      turnIdx: 1,
      durationMs: 88,
      spanId: 'span-s-tool-1',
      input: { entry_id: 'ENT-1001' },
      output: { id: 'ENT-1001', customer: 'Priya Shah', notes: 'Asked about order delay' },
    },
    {
      id: 'e-s-4',
      ts: ISO(118),
      agent: 'A',
      type: 'db',
      name: 'read entries',
      status: 'ok',
      turnIdx: 1,
      durationMs: 12,
    },
    {
      id: 'e-s-5',
      ts: ISO(117),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 2,
      durationMs: 18,
    },
    {
      id: 'e-s-6',
      ts: ISO(116),
      agent: 'A',
      type: 'skill',
      name: 'confirm_before_write',
      status: 'ok',
      turnIdx: 3,
      durationMs: 30,
      spanId: 'span-s-skill-1',
      input: { entry_id: 'ENT-1001' },
    },
    {
      id: 'e-s-7',
      ts: ISO(115),
      agent: 'A',
      type: 'tool',
      name: 'record_entry',
      status: 'ok',
      turnIdx: 3,
      durationMs: 94,
      spanId: 'span-s-tool-2',
      input: {
        entry_id: 'ENT-1001',
        note: 'Customer confirmed the delay was resolved.',
      },
      output: { ok: true },
    },
    {
      id: 'e-s-8',
      ts: ISO(115),
      agent: 'A',
      type: 'db',
      name: 'write entries',
      status: 'ok',
      turnIdx: 3,
      durationMs: 16,
    },
  ]
}

const SUCCESS_TURNS: Turn[] = [
  {
    idx: 0,
    speaker: 'B',
    text: 'Can you fetch entry ENT-1001 for me?',
    ts: ISO(120),
    eventIds: ['e-s-1'],
  },
  {
    idx: 1,
    speaker: 'A',
    text: 'I found ENT-1001 for Priya Shah. Status is open, with a note about an order delay. How can I help?',
    ts: ISO(118),
    eventIds: ['e-s-2', 'e-s-3', 'e-s-4'],
  },
  {
    idx: 2,
    speaker: 'B',
    text: 'Please record that I confirmed the delay was resolved.',
    ts: ISO(117),
    eventIds: ['e-s-5'],
  },
  {
    idx: 3,
    speaker: 'A',
    text: 'Recorded. ENT-1001 now includes your confirmation that the delay was resolved.',
    ts: ISO(115),
    eventIds: ['e-s-6', 'e-s-7', 'e-s-8'],
  },
]

function successFinalDb() {
  const db = cloneSeed() as { entries: { id: string; notes: string }[] }
  db.entries[0].notes = 'Asked about order delay. Customer confirmed the delay was resolved.'
  return db
}

export function sessionSuccess(): Session {
  const events = successEvents()
  return {
    id: 'sim-success',
    kind: 'simulation',
    status: 'completed',
    createdAt: ISO(125),
    endedAt: ISO(114),
    durationSeconds: 48,
    tokens: 1840,
    costUsd: 0.042,
    environment: envSnapshot({ current: successFinalDb(), final: successFinalDb() }),
    scenario: 'Fetch ENT-1001, then record that the delay was resolved.',
    maxTurns: 8,
    metricsSuiteId: 'suite-records',
    agentA: mainAgentConfig(),
    agentB: testAgentConfig(),
    turns: SUCCESS_TURNS,
    events,
    issues: [],
    reliability: [
      { kind: 'tool', name: 'get_entry', calls: 1, failures: 0, avgLatencyMs: 88 },
      { kind: 'tool', name: 'record_entry', calls: 1, failures: 0, avgLatencyMs: 94 },
      { kind: 'skill', name: 'confirm_before_write', calls: 1, failures: 0 },
    ],
    eventsChecked: { tool: 2, skill: 1, api: 0, rag: 0 },
    results: SUCCESS_RESULTS,
    traces: tracesFor(events),
  }
}

export function sessionWriteSkipped(): Session {
  const events: ActivityEvent[] = [
    {
      id: 'e-w-1',
      ts: ISO(90),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 0,
    },
    {
      id: 'e-w-2',
      ts: ISO(89),
      agent: 'A',
      type: 'tool',
      name: 'get_entry',
      status: 'ok',
      turnIdx: 1,
      durationMs: 70,
      input: { entry_id: 'ENT-1001' },
      output: { id: 'ENT-1001', customer: 'Priya Shah' },
    },
    {
      id: 'e-w-3',
      ts: ISO(88),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 2,
    },
    {
      id: 'e-w-4',
      ts: ISO(87),
      agent: 'A',
      type: 'llm',
      name: 'gpt-4.1',
      status: 'ok',
      turnIdx: 3,
      durationMs: 310,
    },
  ]
  const issues: Issue[] = [
    {
      id: 'iss-missing-write',
      severity: 'error',
      category: 'expected_action_missing',
      source: 'rule',
      agent: 'A',
      title: 'Write was never recorded',
      whatHappened: 'The customer asked to record feedback, but `record_entry` was never called.',
      whatToCheck: 'Confirm the write tool is attached and the confirm-before-write skill is followed through to the tool call.',
      turnIdx: 3,
      eventIds: ['e-w-4'],
      configRef: { agent: 'A', section: 'tools', itemId: 'record_entry' },
      status: 'open',
    },
  ]
  return {
    id: 'sim-write-skipped',
    kind: 'simulation',
    status: 'completed',
    createdAt: ISO(95),
    endedAt: ISO(86),
    durationSeconds: 36,
    tokens: 1210,
    costUsd: 0.028,
    environment: envSnapshot({ current: cloneSeed(), final: cloneSeed() }),
    scenario: 'Fetch ENT-1001, then record that the delay was resolved.',
    maxTurns: 8,
    metricsSuiteId: 'suite-records',
    agentA: mainAgentConfig(),
    agentB: testAgentConfig(),
    turns: [
      {
        idx: 0,
        speaker: 'B',
        text: 'Please fetch ENT-1001.',
        ts: ISO(90),
        eventIds: ['e-w-1'],
      },
      {
        idx: 1,
        speaker: 'A',
        text: 'ENT-1001 belongs to Priya Shah and is still open.',
        ts: ISO(89),
        eventIds: ['e-w-2'],
      },
      {
        idx: 2,
        speaker: 'B',
        text: 'Record that the delay was resolved.',
        ts: ISO(88),
        eventIds: ['e-w-3'],
      },
      {
        idx: 3,
        speaker: 'A',
        text: "I'll make a note of that for you.",
        ts: ISO(87),
        eventIds: ['e-w-4'],
      },
    ],
    events,
    issues,
    reliability: [
      { kind: 'tool', name: 'get_entry', calls: 1, failures: 0, avgLatencyMs: 70 },
      { kind: 'tool', name: 'record_entry', calls: 0, failures: 0 },
    ],
    eventsChecked: { tool: 1, skill: 0, api: 0, rag: 0 },
    results: {
      accuracy: 0.34,
      experience: 0.61,
      metrics: [
        {
          name: 'Task completion',
          score: 0,
          passed: false,
          kind: 'deterministic',
          axis: 'accuracy',
          rationale: 'Database is unchanged; the required write never happened.',
        },
        {
          name: 'Faithfulness',
          score: 0.7,
          passed: true,
          kind: 'llm_judge',
          axis: 'accuracy',
        },
        {
          name: 'Conversation progression',
          score: 0.55,
          passed: false,
          kind: 'llm_judge',
          axis: 'experience',
          rationale: 'The agent acknowledged the write without performing it.',
        },
        {
          name: 'Conciseness',
          score: 0.8,
          passed: true,
          kind: 'llm_judge',
          axis: 'experience',
        },
      ],
      outcome: {
        dbMatch: false,
        dbDiff: { added: [], changed: [], removed: [] },
        communicateChecks: [
          { text: 'Told the customer the entry was fetched', passed: true },
          { text: 'Confirmed that feedback was recorded', passed: false },
        ],
      },
    },
    traces: tracesFor(events),
  }
}

function breakageIssues(prefix: string, rememberedApi = false): Issue[] {
  return [
    {
      id: `${prefix}-tool-fail`,
      severity: 'error',
      category: 'tool_failed',
      source: 'rule',
      agent: 'A',
      title: 'get_entry failed',
      whatHappened: 'Tool `get_entry` returned an error when fetching ENT-1001.',
      whatToCheck: 'Inspect the records-DB connection and retry the read with a valid entry_id.',
      turnIdx: 1,
      eventIds: [`${prefix}-e-tool-fail`],
      configRef: { agent: 'A', section: 'tools', itemId: 'get_entry' },
      status: 'open',
    },
    {
      id: `${prefix}-bad-args`,
      severity: 'error',
      category: 'invalid_tool_args',
      source: 'rule',
      agent: 'A',
      title: 'record_entry received a number',
      whatHappened: 'Tool requires `entry_id` (string); the agent sent a number.',
      whatToCheck: 'Update the prompt or skill so entry ids stay strings like ENT-1001.',
      turnIdx: 3,
      eventIds: [`${prefix}-e-bad-args`],
      configRef: { agent: 'A', section: 'tools', itemId: 'record_entry' },
      status: 'open',
    },
    {
      id: `${prefix}-skill`,
      severity: 'warning',
      category: 'skill_misuse',
      source: 'rule',
      agent: 'A',
      title: 'Confirm-before-write skipped required input',
      whatHappened: 'Skill invoked without required input `order_id`.',
      whatToCheck: 'Review the Confirm before write skill and pass every required field.',
      turnIdx: 3,
      eventIds: [`${prefix}-e-skill`],
      configRef: { agent: 'A', section: 'skills', itemId: 'confirm_before_write' },
      status: 'open',
    },
    {
      id: `${prefix}-api`,
      severity: 'error',
      category: 'external_api_failure',
      source: 'rule',
      agent: 'A',
      title: 'orders-api returned 503',
      whatHappened: 'HTTP GET orders-api failed with 503 after 2 retries.',
      whatToCheck: 'Verify the credential for `orders-api` and whether the host is reachable from the sandbox.',
      turnIdx: 5,
      eventIds: [`${prefix}-e-api`],
      configRef: { agent: 'A', section: 'tools', itemId: 'orders-api' },
      status: rememberedApi ? 'dismissed' : 'open',
      dismissedAt: rememberedApi ? ISO(400) : undefined,
      rememberedFromSessionId: rememberedApi ? 'sim-prior' : undefined,
      dismissReason: rememberedApi ? 'Known staging outage' : undefined,
    },
  ]
}

function breakageEvents(prefix: string): ActivityEvent[] {
  return [
    {
      id: `${prefix}-e-msg-0`,
      ts: ISO(60),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 0,
    },
    {
      id: `${prefix}-e-tool-fail`,
      ts: ISO(59),
      agent: 'A',
      type: 'tool',
      name: 'get_entry',
      status: 'error',
      turnIdx: 1,
      durationMs: 140,
      spanId: `${prefix}-span-tool-fail`,
      input: { entry_id: 'ENT-1001' },
      error: { message: 'records-db timeout', code: 'TOOL_ERROR' },
    },
    {
      id: `${prefix}-e-msg-2`,
      ts: ISO(58),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 2,
    },
    {
      id: `${prefix}-e-skill`,
      ts: ISO(57),
      agent: 'A',
      type: 'skill',
      name: 'confirm_before_write',
      status: 'error',
      turnIdx: 3,
      durationMs: 22,
      spanId: `${prefix}-span-skill`,
      input: {},
      error: { message: 'Missing required input order_id' },
    },
    {
      id: `${prefix}-e-bad-args`,
      ts: ISO(57),
      agent: 'A',
      type: 'tool',
      name: 'record_entry',
      status: 'error',
      turnIdx: 3,
      durationMs: 18,
      spanId: `${prefix}-span-args`,
      input: { entry_id: 1001, note: 'resolved' },
      error: { message: 'entry_id must be a string' },
    },
    {
      id: `${prefix}-e-msg-4`,
      ts: ISO(56),
      agent: 'B',
      type: 'message',
      name: 'user_turn',
      status: 'ok',
      turnIdx: 4,
    },
    {
      id: `${prefix}-e-api`,
      ts: ISO(55),
      agent: 'A',
      type: 'api',
      name: 'orders_lookup',
      status: 'error',
      turnIdx: 5,
      durationMs: 2400,
      spanId: `${prefix}-span-api`,
      api: { method: 'GET', host: 'orders-api', statusCode: 503, retries: 2 },
      error: { message: '503 Service Unavailable', code: 'HTTP_503' },
    },
    {
      id: `${prefix}-e-rag`,
      ts: ISO(55),
      agent: 'A',
      type: 'rag',
      name: 'kb-orders',
      status: 'ok',
      turnIdx: 5,
      durationMs: 60,
      input: { query: 'order delay policy' },
      output: { hits: [{ title: 'Delay SLA', score: 0.62 }] },
    },
  ]
}

function sessionBreakage(id: string, agentId: string, rememberedApi: boolean): Session {
  const prefix = id
  const events = breakageEvents(prefix)
  const issues = breakageIssues(prefix, rememberedApi)
  const traces = tracesFor(events)
  traces.A = traces.A.map((span) => {
    const issue = issues.find((i) => i.eventIds.includes(span.eventId || ''))
    return issue ? { ...span, issueId: issue.id } : span
  })
  return {
    id,
    kind: 'simulation',
    status: 'failed',
    createdAt: ISO(id === 'sim-breakage' ? 62 : 40),
    endedAt: ISO(id === 'sim-breakage' ? 54 : 32),
    durationSeconds: 71,
    tokens: 2104,
    costUsd: 0.051,
    environment: envSnapshot({ current: cloneSeed(), final: cloneSeed() }),
    scenario: 'Fetch ENT-1001, then record that the delay was resolved.',
    maxTurns: 8,
    metricsSuiteId: 'suite-records',
    agentA: mainAgentConfig({
      platformAgentId: agentId,
      name: agentId === 'agent-records-bot-alt' ? 'Records Assistant (staging)' : 'Records Assistant',
    }),
    agentB: testAgentConfig(),
    turns: [
      { idx: 0, speaker: 'B', text: 'Fetch ENT-1001.', ts: ISO(60), eventIds: [`${prefix}-e-msg-0`] },
      {
        idx: 1,
        speaker: 'A',
        text: "I couldn't fetch that entry just now. Let me try another way.",
        ts: ISO(59),
        eventIds: [`${prefix}-e-tool-fail`],
      },
      {
        idx: 2,
        speaker: 'B',
        text: 'Please record that the delay was resolved.',
        ts: ISO(58),
        eventIds: [`${prefix}-e-msg-2`],
      },
      {
        idx: 3,
        speaker: 'A',
        text: 'Trying to save that now.',
        ts: ISO(57),
        eventIds: [`${prefix}-e-skill`, `${prefix}-e-bad-args`],
      },
      {
        idx: 4,
        speaker: 'B',
        text: 'Can you look up the related order as well?',
        ts: ISO(56),
        eventIds: [`${prefix}-e-msg-4`],
      },
      {
        idx: 5,
        speaker: 'A',
        text: 'The orders service is unavailable. I can retry in a moment.',
        ts: ISO(55),
        eventIds: [`${prefix}-e-api`, `${prefix}-e-rag`],
      },
    ],
    events,
    issues,
    reliability: [
      { kind: 'tool', name: 'get_entry', calls: 1, failures: 1, avgLatencyMs: 140, topError: 'records-db timeout' },
      { kind: 'tool', name: 'record_entry', calls: 1, failures: 1, avgLatencyMs: 18, topError: 'entry_id must be a string' },
      { kind: 'skill', name: 'confirm_before_write', calls: 1, failures: 1, topError: 'Missing required input order_id' },
      { kind: 'api', name: 'orders-api', calls: 1, failures: 1, avgLatencyMs: 2400, topError: '503' },
    ],
    eventsChecked: { tool: 2, skill: 1, api: 1, rag: 1 },
    results: {
      accuracy: 0.18,
      experience: 0.44,
      metrics: [
        {
          name: 'Task completion',
          score: 0,
          passed: false,
          kind: 'deterministic',
          axis: 'accuracy',
        },
        {
          name: 'Faithfulness',
          score: 0.4,
          passed: false,
          kind: 'llm_judge',
          axis: 'accuracy',
        },
        {
          name: 'Conversation progression',
          score: 0.35,
          passed: false,
          kind: 'llm_judge',
          axis: 'experience',
        },
        {
          name: 'Conciseness',
          score: 0.7,
          passed: true,
          kind: 'llm_judge',
          axis: 'experience',
        },
      ],
      outcome: {
        dbMatch: false,
        dbDiff: { added: [], changed: [], removed: [] },
        communicateChecks: [
          { text: 'Told the customer the entry was fetched', passed: false },
          { text: 'Confirmed that feedback was recorded', passed: false },
        ],
      },
    },
    traces,
  }
}

export function sessionBreakageMain(): Session {
  return sessionBreakage('sim-breakage', 'agent-records-bot', true)
}

export function sessionBreakageAlt(): Session {
  return sessionBreakage('sim-breakage-alt', 'agent-records-bot-alt', false)
}

export function sessionManualHealthy(): Session {
  const events: ActivityEvent[] = [
    {
      id: 'e-m-1',
      ts: ISO(30),
      agent: 'A',
      type: 'message',
      name: 'human_turn',
      status: 'ok',
      turnIdx: 0,
    },
    {
      id: 'e-m-2',
      ts: ISO(29),
      agent: 'A',
      type: 'tool',
      name: 'get_entry',
      status: 'ok',
      turnIdx: 1,
      durationMs: 64,
      input: { entry_id: 'ENT-1001' },
      output: { id: 'ENT-1001', customer: 'Priya Shah' },
    },
    {
      id: 'e-m-3',
      ts: ISO(28),
      agent: 'A',
      type: 'message',
      name: 'human_turn',
      status: 'ok',
      turnIdx: 2,
    },
    {
      id: 'e-m-4',
      ts: ISO(27),
      agent: 'A',
      type: 'tool',
      name: 'record_entry',
      status: 'ok',
      turnIdx: 3,
      durationMs: 80,
      input: { entry_id: 'ENT-1001', note: 'Checked in via playground chat.' },
      output: { ok: true },
    },
    {
      id: 'e-m-5',
      ts: ISO(27),
      agent: 'A',
      type: 'db',
      name: 'write entries',
      status: 'ok',
      turnIdx: 3,
    },
  ]
  const db = successFinalDb()
  return {
    id: 'chat-healthy',
    kind: 'manual',
    status: 'idle',
    createdAt: ISO(32),
    durationSeconds: 94,
    tokens: 640,
    costUsd: 0.011,
    environment: envSnapshot({ current: db, final: db }),
    agentA: mainAgentConfig(),
    chatTarget: 'A',
    turns: [
      { idx: 0, speaker: 'human', text: 'Fetch ENT-1001.', ts: ISO(30), eventIds: ['e-m-1'] },
      {
        idx: 1,
        speaker: 'A',
        text: 'ENT-1001 is Priya Shah, currently open.',
        ts: ISO(29),
        eventIds: ['e-m-2'],
      },
      {
        idx: 2,
        speaker: 'human',
        text: 'Record that I checked in via playground chat.',
        ts: ISO(28),
        eventIds: ['e-m-3'],
      },
      {
        idx: 3,
        speaker: 'A',
        text: 'Saved. The entry now includes your check-in note.',
        ts: ISO(27),
        eventIds: ['e-m-4', 'e-m-5'],
      },
    ],
    events,
    issues: [],
    reliability: [
      { kind: 'tool', name: 'get_entry', calls: 1, failures: 0, avgLatencyMs: 64 },
      { kind: 'tool', name: 'record_entry', calls: 1, failures: 0, avgLatencyMs: 80 },
    ],
    eventsChecked: { tool: 2, skill: 0, api: 0, rag: 0 },
    traces: tracesFor(events),
  }
}

export function sessionManualFailure(): Session {
  const events: ActivityEvent[] = [
    {
      id: 'e-f-1',
      ts: ISO(18),
      agent: 'A',
      type: 'message',
      name: 'human_turn',
      status: 'ok',
      turnIdx: 0,
    },
    {
      id: 'e-f-2',
      ts: ISO(17),
      agent: 'A',
      type: 'api',
      name: 'orders_lookup',
      status: 'error',
      turnIdx: 1,
      durationMs: 1800,
      api: { method: 'GET', host: 'orders-api', statusCode: 500, retries: 1 },
      error: { message: '500 from external API' },
    },
    {
      id: 'e-f-3',
      ts: ISO(16),
      agent: 'A',
      type: 'message',
      name: 'human_turn',
      status: 'ok',
      turnIdx: 3,
    },
    {
      id: 'e-f-4',
      ts: ISO(15),
      agent: 'A',
      type: 'tool',
      name: 'get_entry',
      status: 'ok',
      turnIdx: 4,
      durationMs: 55,
      input: { entry_id: 'ENT-1001' },
      output: { id: 'ENT-1001' },
    },
  ]
  const issues: Issue[] = [
    {
      id: 'iss-live-api',
      severity: 'error',
      category: 'external_api_failure',
      source: 'rule',
      agent: 'A',
      title: 'orders-api returned 500',
      whatHappened: 'Tool `orders_lookup` failed: 500 from external API.',
      whatToCheck: 'Verify the credential for `orders-api`.',
      turnIdx: 1,
      eventIds: ['e-f-2'],
      configRef: { agent: 'A', section: 'tools', itemId: 'orders-api' },
      status: 'open',
    },
    {
      id: 'iss-user-flag',
      severity: 'warning',
      category: 'user_flagged',
      source: 'user',
      agent: 'A',
      title: 'Reply flagged as wrong',
      whatHappened: 'You marked the agent reply as wrong: it claimed the order was found after the API failed.',
      whatToCheck: 'Tighten the prompt so a failed lookup is not described as success.',
      turnIdx: 1,
      eventIds: ['e-f-2'],
      configRef: { agent: 'A', section: 'prompt' },
      status: 'open',
    },
  ]
  return {
    id: 'chat-live-failure',
    kind: 'manual',
    status: 'active',
    createdAt: ISO(20),
    durationSeconds: 210,
    tokens: 980,
    costUsd: 0.019,
    environment: envSnapshot({ current: cloneSeed(), final: cloneSeed() }),
    agentA: mainAgentConfig(),
    chatTarget: 'A',
    configHistory: [{ ts: ISO(16), summary: 'Lowered temperature to 0.1' }],
    turns: [
      { idx: 0, speaker: 'human', text: 'Look up the related order for ENT-1001.', ts: ISO(18), eventIds: ['e-f-1'] },
      {
        idx: 1,
        speaker: 'A',
        text: 'The order service failed. I can still fetch the local record.',
        ts: ISO(17),
        eventIds: ['e-f-2'],
        flaggedByUser: true,
        branchId: 'main',
      },
      {
        idx: 2,
        speaker: 'A',
        text: '',
        ts: ISO(16),
        divider: 'config_changed',
        dividerSummary: 'Temperature set to 0.1',
      },
      {
        idx: 3,
        speaker: 'human',
        text: 'Just fetch the local entry then.',
        ts: ISO(16),
        eventIds: ['e-f-3'],
        branchId: 'retry',
      },
      {
        idx: 4,
        speaker: 'A',
        text: 'Fetched ENT-1001 from the records DB.',
        ts: ISO(15),
        eventIds: ['e-f-4'],
        branchId: 'retry',
      },
    ],
    events,
    issues,
    reliability: [
      { kind: 'api', name: 'orders-api', calls: 1, failures: 1, avgLatencyMs: 1800, topError: '500' },
      { kind: 'tool', name: 'get_entry', calls: 1, failures: 0, avgLatencyMs: 55 },
    ],
    eventsChecked: { tool: 1, skill: 0, api: 1, rag: 0 },
    traces: tracesFor(events),
    activeBranchId: 'retry',
  }
}

export function sessionForked(): Session {
  const source = sessionBreakageMain()
  return {
    ...source,
    id: 'chat-forked',
    kind: 'manual',
    status: 'idle',
    createdAt: ISO(10),
    chatTarget: 'A',
    forkedFrom: { sessionId: 'sim-breakage', turnIdx: 1 },
    agentB: undefined,
    results: undefined,
    turns: [
      ...source.turns.slice(0, 2),
      {
        idx: 2,
        speaker: 'A',
        text: '',
        ts: ISO(10),
        divider: 'branch',
        dividerSummary: 'Forked from sim-breakage at turn 1',
      },
    ],
  }
}

export const SEEDED_DISMISSALS: AgentDismissal[] = [
  {
    agentId: 'agent-records-bot',
    signature: 'external_api_failure:orders-api',
    reason: 'Known staging outage',
    dismissedAt: ISO(400),
    sourceSessionId: 'sim-prior',
  },
]

export function allFixtureSessions(): Session[] {
  return [
    sessionSuccess(),
    sessionWriteSkipped(),
    sessionBreakageMain(),
    sessionBreakageAlt(),
    sessionManualHealthy(),
    sessionManualFailure(),
    sessionForked(),
  ]
}
