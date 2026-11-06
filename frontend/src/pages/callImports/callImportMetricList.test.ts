import { describe, expect, it } from 'vitest'
import {
  callImportEvalSurface,
  metricsForCallImportRunEvaluation,
  type CallImportMetricRow,
} from './callImportMetricList'

function row(overrides: Partial<CallImportMetricRow> & { id: string; name: string }): CallImportMetricRow {
  return {
    enabled: true,
    ...overrides,
  }
}

describe('callImportMetricList', () => {
  it('maps chat content_modality to chat_agent surface', () => {
    expect(callImportEvalSurface('chat')).toBe('chat_agent')
    expect(callImportEvalSurface('CHAT')).toBe('chat_agent')
    expect(callImportEvalSurface(null)).toBe('agent')
    expect(callImportEvalSurface(undefined)).toBe('agent')
  })

  it('keeps golden voice metric on voice import', () => {
    const metrics = [
      row({
        id: '1',
        name: 'Golden',
        enabled_surfaces: ['agent'],
        agent_ids: [],
        scenario_ids: [],
      }),
    ]
    expect(metricsForCallImportRunEvaluation(metrics, 'agent')).toHaveLength(1)
  })

  it('keeps golden chat metric on chat import', () => {
    const metrics = [
      row({
        id: '1',
        name: 'Golden chat',
        enabled_surfaces: ['chat_agent'],
        agent_ids: [],
        scenario_ids: [],
      }),
    ]
    expect(metricsForCallImportRunEvaluation(metrics, 'chat_agent')).toHaveLength(1)
  })

  it('keeps agent and scenario scoped chat metric on chat import', () => {
    const metrics = [
      row({
        id: '1',
        name: 'Scoped',
        enabled_surfaces: ['chat_agent'],
        agent_ids: ['agent-a'],
        scenario_ids: ['scenario-b'],
      }),
    ]
    expect(metricsForCallImportRunEvaluation(metrics, 'chat_agent')).toHaveLength(1)
  })

  it('excludes chat-only metric from voice import surface filter', () => {
    const metrics = [
      row({
        id: '1',
        name: 'Chat only',
        enabled_surfaces: ['chat_agent'],
      }),
    ]
    expect(metricsForCallImportRunEvaluation(metrics, 'agent')).toHaveLength(0)
  })

  it('treats empty enabled_surfaces as eligible on agent and chat_agent', () => {
    const metrics = [row({ id: '1', name: 'Legacy', enabled_surfaces: [] })]
    expect(metricsForCallImportRunEvaluation(metrics, 'agent')).toHaveLength(1)
    expect(metricsForCallImportRunEvaluation(metrics, 'chat_agent')).toHaveLength(1)
  })
})
