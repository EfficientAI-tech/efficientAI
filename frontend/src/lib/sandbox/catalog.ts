import type {
  AgentConfig,
  Catalog,
  HarnessConfig,
  RagAttachment,
  SandboxEnvironment,
  SkillDef,
  ToolDef,
} from './types'

export const TOOL_GET_ENTRY: ToolDef = {
  id: 'get_entry',
  name: 'get_entry',
  description: 'Fetch a records-DB entry by id.',
  access: 'read',
  kind: 'environment',
  schema: {
    type: 'object',
    required: ['entry_id'],
    properties: { entry_id: { type: 'string' } },
  },
}

export const TOOL_RECORD_ENTRY: ToolDef = {
  id: 'record_entry',
  name: 'record_entry',
  description: 'Write a note onto an existing records-DB entry.',
  access: 'write',
  kind: 'environment',
  schema: {
    type: 'object',
    required: ['entry_id', 'note'],
    properties: {
      entry_id: { type: 'string' },
      note: { type: 'string' },
    },
  },
}

export const TOOL_LIST_ENTRIES: ToolDef = {
  id: 'list_entries',
  name: 'list_entries',
  description: 'List entries in the records DB.',
  access: 'read',
  kind: 'environment',
  schema: { type: 'object', properties: { status: { type: 'string' } } },
}

export const TOOL_ORDERS_LOOKUP: ToolDef = {
  id: 'orders_lookup',
  name: 'orders_lookup',
  description: 'Look up an order on the external orders API.',
  access: 'read',
  kind: 'http',
  schema: {
    type: 'object',
    required: ['order_id'],
    properties: { order_id: { type: 'string' } },
  },
}

export const SKILL_CONFIRM_WRITE: SkillDef = {
  id: 'confirm_before_write',
  name: 'Confirm before write',
  markdown:
    'Before any write tool, restated the change, wait for explicit user confirmation, then call the write tool with `entry_id` as a string.',
}

export const SKILL_FETCH_FIRST: SkillDef = {
  id: 'fetch_before_advise',
  name: 'Fetch before advising',
  markdown: 'Always fetch the live entry with `get_entry` before describing its contents.',
}

export const HARNESS_DEFAULT: HarnessConfig = {
  id: 'default-tool-calling',
  name: 'Default tool-calling',
  settings: { maxSteps: '8' },
}

export const HARNESS_REACT: HarnessConfig = {
  id: 'react',
  name: 'ReAct',
  settings: { maxSteps: '12', thought: 'true' },
}

export const RAG_ORDERS: RagAttachment = {
  collectionId: 'kb-orders',
  name: 'Orders knowledge base',
  docCount: 42,
  topK: 4,
  threshold: 0.35,
}

export const RECORDS_SEED = {
  entries: [
    {
      id: 'ENT-1001',
      customer: 'Priya Shah',
      status: 'open',
      notes: 'Asked about order delay',
    },
    {
      id: 'ENT-1002',
      customer: 'James Cole',
      status: 'closed',
      notes: 'Refund issued',
    },
  ],
}

export const RECORDS_ENV: SandboxEnvironment = {
  id: 'env-records',
  name: 'Records DB',
  domain: 'Retail',
  description: 'Seeded customer-service records with fetch and record tools.',
  policy:
    '# Records policy\n\n- Read entries only through `get_entry` or `list_entries`.\n- Never write without explicit user confirmation.\n- `entry_id` is always a string (e.g. `ENT-1001`).\n- After recording feedback, confirm the updated note to the customer.',
  seed: RECORDS_SEED,
  toolIds: ['get_entry', 'record_entry', 'list_entries', 'orders_lookup'],
}

export function cloneSeed(): Record<string, unknown> {
  return JSON.parse(JSON.stringify(RECORDS_SEED)) as Record<string, unknown>
}

export function mainAgentConfig(overrides?: Partial<AgentConfig>): AgentConfig {
  return {
    name: 'Records Assistant',
    platformAgentId: 'agent-records-bot',
    prompt:
      'You are the company records assistant. Fetch entries when asked, confirm before writing, and record customer feedback with record_entry.',
    llm: {
      provider: 'openai',
      model: 'gpt-4.1',
      credentialId: 'cred-openai-prod',
      temperature: 0.2,
      maxTokens: 1024,
    },
    framework: 'native',
    tools: [TOOL_GET_ENTRY, TOOL_RECORD_ENTRY, TOOL_LIST_ENTRIES, TOOL_ORDERS_LOOKUP],
    skills: [SKILL_CONFIRM_WRITE, SKILL_FETCH_FIRST],
    harness: HARNESS_DEFAULT,
    rag: [RAG_ORDERS],
    ...overrides,
  }
}

export function testAgentConfig(overrides?: Partial<AgentConfig>): AgentConfig {
  return {
    name: 'Simulated customer',
    platformAgentId: 'agent-test-customer',
    prompt:
      'You are Priya Shah. Ask the assistant to fetch ENT-1001, then ask them to record that the delay was resolved.',
    llm: {
      provider: 'anthropic',
      model: 'claude-sonnet-4',
      credentialId: 'cred-anthropic-test',
      temperature: 0.7,
      maxTokens: 512,
    },
    framework: 'native',
    tools: [],
    skills: [],
    harness: HARNESS_DEFAULT,
    rag: [],
    ...overrides,
  }
}

export const SANDBOX_CATALOG: Catalog = {
  environments: [RECORDS_ENV],
  tools: [TOOL_GET_ENTRY, TOOL_RECORD_ENTRY, TOOL_LIST_ENTRIES, TOOL_ORDERS_LOOKUP],
  skills: [SKILL_CONFIRM_WRITE, SKILL_FETCH_FIRST],
  harnesses: [HARNESS_DEFAULT, HARNESS_REACT],
  ragCollections: [RAG_ORDERS],
  metricsSuites: [
    {
      id: 'suite-records',
      name: 'Records accuracy + experience',
      description: 'Task completion, faithfulness, progression, conciseness.',
    },
  ],
  platformAgents: [
    { id: 'agent-records-bot', name: 'Records Assistant', role: 'A', config: mainAgentConfig() },
    {
      id: 'agent-records-bot-alt',
      name: 'Records Assistant (staging)',
      role: 'A',
      config: mainAgentConfig({
        name: 'Records Assistant (staging)',
        platformAgentId: 'agent-records-bot-alt',
      }),
    },
    { id: 'agent-test-customer', name: 'Simulated customer', role: 'B', config: testAgentConfig() },
  ],
  llmOptions: [
    { provider: 'openai', models: ['gpt-4.1', 'gpt-4.1-mini'] },
    { provider: 'anthropic', models: ['claude-sonnet-4', 'claude-haiku-4'] },
  ],
}
