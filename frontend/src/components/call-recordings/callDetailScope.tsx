import { getVoiceProviderCapabilities } from '../../lib/voiceProviderRegistry'

export type EvaluatorCallScope = {
  agentName?: string | null
  personaName?: string | null
  personaTtsLine?: string | null
  platform?: string | null
  chatSimulation?: boolean
}

function platformLabel(platform?: string | null): string | null {
  if (!platform) return null
  return getVoiceProviderCapabilities(platform).label
}

function personaShort(scope: EvaluatorCallScope): string | null {
  if (!scope.personaName?.trim()) return null
  const tts = scope.personaTtsLine?.trim()
  return tts ? `${scope.personaName} · ${tts}` : scope.personaName
}

export function CallDetailScopeTags({
  tags,
  hint,
}: {
  tags: string[]
  hint?: string | null
}) {
  if (!tags.length) return null
  return (
    <div className="mb-3 space-y-1">
      <div className="flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-medium text-gray-600"
          >
            {tag}
          </span>
        ))}
      </div>
      {hint?.trim() ? <p className="text-[11px] leading-snug text-gray-500">{hint}</p> : null}
    </div>
  )
}

export function evaluatorDrawerScopeTags(
  tab:
    | 'transcript'
    | 'analysis'
    | 'cost'
    | 'latency'
    | 'logs'
    | 'pipeline'
    | 'trace'
    | 'waterfall'
    | 'timeline'
    | 'spans',
  scope: EvaluatorCallScope,
): { tags: string[]; hint?: string } {
  const plat = platformLabel(scope.platform)
  const agent = scope.agentName?.trim()
  const caller = personaShort(scope)

  switch (tab) {
    case 'transcript':
      return {
        tags: scope.chatSimulation
          ? [
              'Text conversation',
              agent ? `Agent: ${agent}` : 'Agent under test',
              scope.personaName?.trim() ? `Persona: ${scope.personaName}` : 'Simulated persona',
            ]
          : [
              'Full conversation',
              agent ? `Agent: ${agent}` : 'Agent under test',
              caller ? `Caller: ${caller}` : 'Simulated caller',
            ],
      }
    case 'analysis':
      return {
        tags: ['Post-call summary', plat ? `${plat} or evaluator` : 'Provider / evaluator'],
      }
    case 'cost': {
      const tags = [plat ? `${plat} agent cost` : 'Agent provider cost']
      if (agent) tags.push(agent)
      if (caller) tags.push('Persona cost not reported')
      return { tags }
    }
    case 'latency':
      return {
        tags: [
          plat ? `${plat} agent` : 'Agent provider',
          'Latency',
        ],
      }
    case 'logs':
      return {
        tags: [plat ? `${plat} logs` : 'Provider logs'],
      }
    case 'pipeline':
    case 'trace':
    case 'waterfall':
    case 'timeline':
    case 'spans':
      return {
        tags: ['Persona pipeline', caller ? caller : 'Simulated caller'],
      }
    default:
      return { tags: [] }
  }
}
