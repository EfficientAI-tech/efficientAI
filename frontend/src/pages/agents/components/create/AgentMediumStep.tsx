import { Mic, MessagesSquare } from 'lucide-react'
import type { AgentMedium } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'

interface AgentMediumStepProps {
  value: AgentMedium | null
  onChange: (medium: AgentMedium) => void
  embedded?: boolean
  compact?: boolean
}

const OPTIONS: {
  id: AgentMedium
  label: string
  subtitle: string
  icon: typeof Mic
}[] = [
  { id: 'voice', label: 'Voice', subtitle: 'Phone or platform voice agents', icon: Mic },
  { id: 'chat', label: 'Chat', subtitle: 'Text evals against live or API chat', icon: MessagesSquare },
]

export default function AgentMediumStep({ value, onChange, embedded, compact }: AgentMediumStepProps) {
  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-4xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="What kind of agent?"
          subtitle="Pick voice or chat — connection options come next."
          prominence={compact ? 'entry' : 'default'}
        />
      ) : null}
      <div
        className={`grid grid-cols-2 w-full ${compact ? 'gap-3.5 mt-4' : 'gap-4 mt-6 sm:grid-cols-2'}`}
      >
        {OPTIONS.map((option) => (
          <WizardIconCard
            key={option.id}
            label={option.label}
            subtitle={compact ? option.subtitle : undefined}
            icon={option.icon}
            selected={value === option.id}
            onSelect={() => onChange(option.id)}
            medium={!compact}
            compact={compact}
          />
        ))}
      </div>
    </div>
  )
}
