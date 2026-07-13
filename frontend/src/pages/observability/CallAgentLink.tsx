import { useNavigate } from 'react-router-dom'
import type { MouseEvent } from 'react'

import type { ObservabilityCallAgent, ObservabilityCallData } from '../../types/api'

function getExternalAgentLabel(callData?: ObservabilityCallData | null): string | null {
  if (!callData) return null
  const agentRef = callData._agent_ref
  if (agentRef != null && String(agentRef).trim()) return String(agentRef)
  const agentName = callData.agent_name
  if (agentName != null && String(agentName).trim()) return String(agentName)
  return null
}

export function getCallAgentDisplay(
  agent?: ObservabilityCallAgent | null,
  callData?: ObservabilityCallData | null,
): { label: string; linked: boolean; href?: string } | null {
  if (agent) {
    return {
      label: agent.name,
      linked: true,
      href: `/agents/${agent.agent_id || agent.id}`,
    }
  }
  const external = getExternalAgentLabel(callData)
  if (external) {
    return { label: external, linked: false }
  }
  return null
}

export function CallAgentLink({
  agent,
  callData,
  onClick,
}: {
  agent?: ObservabilityCallAgent | null
  callData?: ObservabilityCallData | null
  onClick?: (e: MouseEvent) => void
}) {
  const navigate = useNavigate()
  const display = getCallAgentDisplay(agent, callData)

  if (!display) {
    return <span className="text-sm text-gray-400">—</span>
  }

  if (display.linked && display.href) {
    return (
      <button
        type="button"
        onClick={(e) => {
          onClick?.(e)
          e.stopPropagation()
          navigate(display.href!)
        }}
        className="text-sm font-medium text-primary-600 hover:text-primary-800 hover:underline text-left"
      >
        {display.label}
      </button>
    )
  }

  return (
    <span className="text-sm text-gray-600" title="External agent (unlinked)">
      {display.label}
      <span className="ml-1 text-xs text-gray-400">(external)</span>
    </span>
  )
}
