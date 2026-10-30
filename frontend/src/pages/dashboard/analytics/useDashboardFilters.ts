import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAgentStore } from '../../../store/agentStore'
import type { Agent } from '../../../store/agentStore'
import { parseDashboardSection, parseFailureKind, type DashboardSection, type FailureKind } from './dashboardSection'
import { isMockDataEnabled } from './mockMode'
import {
  parseIsoDay,
  parseRange,
  parseSource,
  resolveDashboardWindow,
  type DashboardRange,
  type DashboardSource,
} from './timeBuckets'

export function useDashboardFilters() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedAgent = useAgentStore((s) => s.selectedAgent)
  const setSelectedAgent = useAgentStore((s) => s.setSelectedAgent)

  const agentParam = searchParams.get('agent')
  const agentId = !agentParam || agentParam === 'all' ? null : agentParam
  const range = parseRange(searchParams.get('range'))
  const source = parseSource(searchParams.get('source'))
  const metricId = searchParams.get('metric')
  const callId = searchParams.get('call')
  const scenarioId = searchParams.get('scenario')
  const label = searchParams.get('label')
  const failing = searchParams.get('failing') === '1'
  const point = searchParams.get('point')
  const since = parseIsoDay(searchParams.get('since'))
  const until = parseIsoDay(searchParams.get('until'))
  const section = parseDashboardSection(searchParams.get('section'))
  const modelId = searchParams.get('model')
  const toolName = searchParams.get('tool')
  const failKind = parseFailureKind(searchParams.get('fail'))
  const window = useMemo(
    () => resolveDashboardWindow(range, since, until),
    [range, since, until],
  )

  const setParams = useCallback(
    (patch: {
      agent?: string | null
      range?: DashboardRange
      source?: DashboardSource
      metric?: string | null
      call?: string | null
      scenario?: string | null
      label?: string | null
      failing?: boolean | null
      point?: string | null
      since?: string | null
      until?: string | null
      section?: DashboardSection | null
      model?: string | null
      tool?: string | null
      fail?: FailureKind | null
    }) => {
      const next = new URLSearchParams(searchParams)
      if (patch.agent !== undefined) {
        if (!patch.agent || patch.agent === 'all') next.delete('agent')
        else next.set('agent', patch.agent)
      }
      if (patch.range) {
        if (patch.range === '7d') next.delete('range')
        else next.set('range', patch.range)
        next.delete('since')
        next.delete('until')
        next.delete('point')
      }
      if (patch.source) {
        if (patch.source === 'simulation') next.delete('source')
        else next.set('source', patch.source)
      }
      if (patch.metric !== undefined) {
        if (!patch.metric) next.delete('metric')
        else next.set('metric', patch.metric)
        next.delete('label')
        next.delete('point')
      }
      if (patch.call !== undefined) {
        if (!patch.call) next.delete('call')
        else next.set('call', patch.call)
      }
      if (patch.scenario !== undefined) {
        if (!patch.scenario) next.delete('scenario')
        else next.set('scenario', patch.scenario)
      }
      if (patch.label !== undefined) {
        if (!patch.label) next.delete('label')
        else next.set('label', patch.label)
      }
      if (patch.failing !== undefined) {
        if (!patch.failing) next.delete('failing')
        else next.set('failing', '1')
      }
      if (patch.point !== undefined) {
        if (!patch.point) next.delete('point')
        else next.set('point', patch.point)
      }
      if (patch.since !== undefined) {
        if (!patch.since) next.delete('since')
        else next.set('since', patch.since)
      }
      if (patch.until !== undefined) {
        if (!patch.until) next.delete('until')
        else next.set('until', patch.until)
      }
      if (patch.section !== undefined) {
        if (!patch.section || patch.section === 'overview') next.delete('section')
        else next.set('section', patch.section)
      }
      if (patch.model !== undefined) {
        if (!patch.model) next.delete('model')
        else next.set('model', patch.model)
      }
      if (patch.tool !== undefined) {
        if (!patch.tool) next.delete('tool')
        else next.set('tool', patch.tool)
      }
      if (patch.fail !== undefined) {
        if (!patch.fail) next.delete('fail')
        else next.set('fail', patch.fail)
      }
      next.delete('view')
      next.delete('tab')
      next.delete('funnel')
      next.delete('customize')
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const selectAgent = useCallback(
    (agent: Agent | null | 'all') => {
      if (agent === 'all' || agent === null) {
        setParams({ agent: 'all', call: null, section: 'overview' })
        return
      }
      setParams({ agent: agent.id, call: null, section: 'agent' })
      if (!isMockDataEnabled() && selectedAgent?.id !== agent.id) {
        void setSelectedAgent(agent)
      }
    },
    [selectedAgent?.id, setParams, setSelectedAgent],
  )

  const openMetric = useCallback(
    (nextMetricId: string | null, nextAgentId?: string | null) => {
      setParams({
        metric: nextMetricId,
        call: null,
        ...(nextAgentId !== undefined ? { agent: nextAgentId } : {}),
      })
    },
    [setParams],
  )

  const openCall = useCallback(
    (nextCallId: string | null) => {
      setParams({ call: nextCallId })
    },
    [setParams],
  )

  const openSection = useCallback(
    (
      next: DashboardSection,
      extras?: { agent?: string | null; model?: string | null; tool?: string | null; fail?: FailureKind | null },
    ) => {
      setParams({
        section: next,
        metric: null,
        call: null,
        model: extras?.model ?? null,
        tool: extras?.tool ?? null,
        fail: extras?.fail ?? null,
        agent: extras?.agent !== undefined ? extras.agent : next === 'agent' ? agentId : null,
      })
    },
    [agentId, setParams],
  )

  return useMemo(
    () => ({
      agentId,
      range,
      source,
      metricId,
      callId,
      scenarioId,
      label,
      failing,
      point,
      since,
      until,
      section,
      modelId,
      toolName,
      failKind,
      window,
      setParams,
      selectAgent,
      openMetric,
      openCall,
      openSection,
    }),
    [
      agentId,
      callId,
      failKind,
      failing,
      label,
      metricId,
      modelId,
      openCall,
      openMetric,
      openSection,
      point,
      range,
      scenarioId,
      section,
      selectAgent,
      setParams,
      since,
      source,
      toolName,
      until,
      window,
    ],
  )
}
