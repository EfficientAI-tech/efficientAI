import { describe, expect, it } from 'vitest'
import { resolveClusterScopeDisplay } from './ClusterScopeHeader'
import type { EvaluationMetricClustersState } from './types'

describe('resolveClusterScopeDisplay', () => {
  it('prefers generation_scope scenario names from the API', () => {
    const state = {
      status: 'completed',
      groups: [],
      discovered_problems: [],
      generated_at_completed_rows: 1,
      llm_calls_used: 0,
      is_stale: false,
      generation_scope: {
        agent_id: 'agent-1',
        agent_name: 'Support Bot',
        scenario_ids: ['s1', 's2'],
        scenario_names: ['Billing', 'Escalation'],
        eligible_call_count: 12,
        selected_call_count: 8,
      },
    } satisfies EvaluationMetricClustersState

    const display = resolveClusterScopeDisplay(state, [], null)
    expect(display?.agentName).toBe('Support Bot')
    expect(display?.scenarioNames).toEqual(['Billing', 'Escalation'])
    expect(display?.selectedCallCount).toBe(8)
    expect(display?.eligibleCallCount).toBe(12)
  })

  it('falls back to URL scope and overview agent names', () => {
    const display = resolveClusterScopeDisplay(
      null,
      [
        {
          agent_id: 'agent-1',
          agent_name: 'Fallback Agent',
          counts: { total: 1, completed: 1, failed: 0, in_progress: 0 },
          suites: [
            {
              suite_id: 'suite-1',
              suite_name: 'Suite',
              agent_id: 'agent-1',
              counts: { total: 1, completed: 1, failed: 0, in_progress: 0 },
              scenarios: [
                {
                  scenario_id: 's1',
                  scenario_name: 'Billing',
                  counts: { total: 1, completed: 1, failed: 0, in_progress: 0 },
                },
              ],
            },
          ],
        },
      ],
      {
        agentId: 'agent-1',
        scenarioIds: ['s1'],
        since: '2026-01-01T00:00:00.000Z',
        until: '2026-01-31T23:59:59.999Z',
      },
    )

    expect(display?.agentName).toBe('Fallback Agent')
    expect(display?.scenarioNames).toEqual(['Billing'])
    expect(display?.dateLabel).toBe('2026-01-01 → 2026-01-31')
  })
})
