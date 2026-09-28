import { Phone, Cloud } from 'lucide-react'
import type { CreateAgentPath } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'
import { WIZARD_EXISTING_PLATFORM_LABEL } from './wizardCopy'

interface VoicePathSelectorProps {
  value: CreateAgentPath
  onChange: (path: CreateAgentPath) => void
  embedded?: boolean
}

const OPTIONS: { id: CreateAgentPath; label: string; icon: typeof Phone }[] = [
  { id: 'telephony', label: 'Telephony', icon: Phone },
  { id: 'platform', label: WIZARD_EXISTING_PLATFORM_LABEL, icon: Cloud },
]

export default function VoicePathSelector({ value, onChange, embedded }: VoicePathSelectorProps) {
  const active = value === 'chat' ? 'telephony' : value

  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="Voice deployment"
          subtitle="Phone numbers or an agent on Vapi, Retell, ElevenLabs, or Smallest."
        />
      ) : null}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-4xl">
        {OPTIONS.map((option) => (
          <WizardIconCard
            key={option.id}
            label={option.label}
            icon={option.icon}
            selected={active === option.id}
            onSelect={() => onChange(option.id)}
            large
          />
        ))}
      </div>
    </div>
  )
}
