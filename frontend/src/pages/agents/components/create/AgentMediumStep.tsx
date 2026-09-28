import { Mic, MessagesSquare } from 'lucide-react'
import type { AgentMedium } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'

interface AgentMediumStepProps {
  value: AgentMedium | null
  onChange: (medium: AgentMedium) => void
  embedded?: boolean
}

const OPTIONS: { id: AgentMedium; label: string; icon: typeof Mic }[] = [
  { id: 'voice', label: 'Voice Agent', icon: Mic },
  { id: 'chat', label: 'Chat Agent', icon: MessagesSquare },
]

export default function AgentMediumStep({ value, onChange, embedded }: AgentMediumStepProps) {
  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-4xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="What kind of agent?"
          subtitle="Pick voice or chat — connection options come next."
        />
      ) : null}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full">
        {OPTIONS.map((option) => (
          <WizardIconCard
            key={option.id}
            label={option.label}
            icon={option.icon}
            selected={value === option.id}
            onSelect={() => onChange(option.id)}
            medium
          />
        ))}
      </div>
    </div>
  )
}
