export type RunStrategy = 'web_bridge' | 'phone_outbound' | 'phone_inbound_manual' | 'unsupported'

export interface EvaluatorForRun {
  id: string
  agent_id?: string | null
  custom_prompt?: string | null
  metric_ids?: string[] | null
}

export interface AgentForRun {
  id: string
  call_medium: string
  call_type: string
  phone_number?: string | null
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
}

export function isCustomEvaluator(evaluator: EvaluatorForRun): boolean {
  return !!evaluator.custom_prompt || !evaluator.agent_id
}

export function getEvaluatorRunStrategy(
  evaluator: EvaluatorForRun,
  agent: AgentForRun | null | undefined
): RunStrategy {
  if (isCustomEvaluator(evaluator)) {
    return evaluator.custom_prompt ? 'web_bridge' : 'unsupported'
  }

  if (!agent) {
    return 'unsupported'
  }

  const callMedium = agent.call_medium || 'phone_call'
  const callType = agent.call_type || 'outbound'

  if (callMedium === 'web_call') {
    return 'web_bridge'
  }

  if (callMedium === 'phone_call') {
    if (callType === 'outbound') {
      return 'phone_outbound'
    }
    if (callType === 'inbound') {
      return 'phone_inbound_manual'
    }
  }

  return 'unsupported'
}

export interface PartitionedEvaluatorsForRun {
  webBridge: EvaluatorForRun[]
  phoneOutbound: EvaluatorForRun[]
  phoneInbound: EvaluatorForRun[]
  unsupported: EvaluatorForRun[]
}

function resolveAgent(
  agentId: string | null | undefined,
  agentsById: Map<string, AgentForRun> | Record<string, AgentForRun>
): AgentForRun | null {
  if (!agentId) return null
  if (agentsById instanceof Map) {
    return agentsById.get(agentId) ?? null
  }
  return agentsById[agentId] ?? null
}

export function partitionEvaluatorsForRun(
  evaluators: EvaluatorForRun[],
  agentsById: Map<string, AgentForRun> | Record<string, AgentForRun>
): PartitionedEvaluatorsForRun {
  const result: PartitionedEvaluatorsForRun = {
    webBridge: [],
    phoneOutbound: [],
    phoneInbound: [],
    unsupported: [],
  }

  for (const evaluator of evaluators) {
    const agent = resolveAgent(evaluator.agent_id, agentsById)
    const strategy = getEvaluatorRunStrategy(evaluator, agent)
    switch (strategy) {
      case 'web_bridge':
        result.webBridge.push(evaluator)
        break
      case 'phone_outbound':
        result.phoneOutbound.push(evaluator)
        break
      case 'phone_inbound_manual':
        result.phoneInbound.push(evaluator)
        break
      default:
        result.unsupported.push(evaluator)
    }
  }

  return result
}

export function buildAgentsById(agents: AgentForRun[]): Record<string, AgentForRun> {
  return Object.fromEntries(agents.map((agent) => [agent.id, agent]))
}

export function getSuiteRunStrategy(suite: {
  agent_call_medium?: string | null
  agent_call_type?: string | null
}): RunStrategy {
  const callMedium = suite.agent_call_medium || 'phone_call'
  const callType = suite.agent_call_type || 'outbound'
  if (callMedium === 'web_call') return 'web_bridge'
  if (callMedium === 'phone_call') {
    if (callType === 'inbound') return 'phone_inbound_manual'
    return 'phone_outbound'
  }
  return 'unsupported'
}
