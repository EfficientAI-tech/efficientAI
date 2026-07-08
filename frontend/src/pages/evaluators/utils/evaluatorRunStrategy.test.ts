import { describe, expect, it } from 'vitest'
import {
  buildAgentsById,
  getEvaluatorRunStrategy,
  isCustomEvaluator,
  partitionEvaluatorsForRun,
  type AgentForRun,
  type EvaluatorForRun,
} from './evaluatorRunStrategy'

const outboundPhoneAgent: AgentForRun = {
  id: 'agent-outbound',
  call_medium: 'phone_call',
  call_type: 'outbound',
  phone_number: '+15551234567',
}

const inboundPhoneAgent: AgentForRun = {
  id: 'agent-inbound',
  call_medium: 'phone_call',
  call_type: 'inbound',
  phone_number: '+15559876543',
}

const webAgent: AgentForRun = {
  id: 'agent-web',
  call_medium: 'web_call',
  call_type: 'outbound',
}

const standardEvaluator: EvaluatorForRun = {
  id: 'eval-1',
  agent_id: 'agent-outbound',
}

describe('isCustomEvaluator', () => {
  it('detects custom evaluators by missing agent', () => {
    expect(isCustomEvaluator({ id: '1', custom_prompt: 'test' })).toBe(true)
  })

  it('detects standard evaluators', () => {
    expect(isCustomEvaluator({ id: '1', agent_id: 'a' })).toBe(false)
  })
})

describe('getEvaluatorRunStrategy', () => {
  it('returns web_bridge for custom prompt evaluators', () => {
    expect(getEvaluatorRunStrategy({ id: '1', custom_prompt: 'prompt' }, null)).toBe('web_bridge')
  })

  it('returns web_bridge for web_call agents', () => {
    expect(
      getEvaluatorRunStrategy({ id: '1', agent_id: webAgent.id }, webAgent)
    ).toBe('web_bridge')
  })

  it('returns phone_outbound for phone outbound agents', () => {
    expect(
      getEvaluatorRunStrategy({ id: '1', agent_id: outboundPhoneAgent.id }, outboundPhoneAgent)
    ).toBe('phone_outbound')
  })

  it('returns phone_inbound_manual for phone inbound agents', () => {
    expect(
      getEvaluatorRunStrategy({ id: '1', agent_id: inboundPhoneAgent.id }, inboundPhoneAgent)
    ).toBe('phone_inbound_manual')
  })

  it('returns unsupported when agent is missing for standard evaluator', () => {
    expect(getEvaluatorRunStrategy(standardEvaluator, null)).toBe('unsupported')
  })
})

describe('partitionEvaluatorsForRun', () => {
  const agentsById = buildAgentsById([outboundPhoneAgent, inboundPhoneAgent, webAgent])

  it('partitions evaluators by strategy', () => {
    const partition = partitionEvaluatorsForRun(
      [
        { id: 'e1', agent_id: 'agent-outbound' },
        { id: 'e2', agent_id: 'agent-inbound' },
        { id: 'e3', agent_id: 'agent-web' },
        { id: 'e4', custom_prompt: 'custom' },
        { id: 'e5', agent_id: 'missing-agent' },
      ],
      agentsById
    )

    expect(partition.phoneOutbound.map((e) => e.id)).toEqual(['e1'])
    expect(partition.phoneInbound.map((e) => e.id)).toEqual(['e2'])
    expect(partition.webBridge.map((e) => e.id)).toEqual(['e3', 'e4'])
    expect(partition.unsupported.map((e) => e.id)).toEqual(['e5'])
  })

  it('works with Map agents lookup', () => {
    const map = new Map(Object.entries(agentsById))
    const partition = partitionEvaluatorsForRun([{ id: 'e1', agent_id: 'agent-inbound' }], map)
    expect(partition.phoneInbound).toHaveLength(1)
  })
})
