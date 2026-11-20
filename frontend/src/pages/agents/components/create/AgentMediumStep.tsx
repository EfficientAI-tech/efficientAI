import { Brain, Mic, MessagesSquare } from 'lucide-react'
import type { AgentMedium } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'
import { useLicenseStore } from '../../../../store/licenseStore'
import { wizardOptionGridClass } from './wizardCopy'

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
  {
    id: 'voice',
    label: 'Voice',
    subtitle: 'Test your voice agents already hosted in production.',
    icon: Mic,
  },
  {
    id: 'chat',
    label: 'Chat',
    subtitle: 'Test your chat agents already hosted in production.',
    icon: MessagesSquare,
  },
  {
    id: 'hosted',
    label: 'Hosted agent from scratch',
    subtitle:
      'Create your production agent from scratch and self improve by simulating them against 100s of scenarios',
    icon: Brain,
  },
]

export default function AgentMediumStep({ value, onChange, embedded, compact }: AgentMediumStepProps) {
  const { isFeatureEnabled, isLoaded } = useLicenseStore()
  const hostedEnabled = !isLoaded || isFeatureEnabled('hosted_agents')
  const visibleOptions = OPTIONS.filter(
    (option) => option.id !== 'hosted' || hostedEnabled,
  )
  const gridClass = wizardOptionGridClass(visibleOptions.length, Boolean(compact))

  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-4xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="What kind of agent?"
          subtitle={
            hostedEnabled
              ? 'Hosted on EfficientAI, voice with telephony or a platform, or external chat.'
              : 'Voice with telephony or a platform, or external chat.'
          }
          prominence={compact ? 'entry' : 'default'}
        />
      ) : null}
      <div className={gridClass}>
        {visibleOptions.map((option) => (
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
