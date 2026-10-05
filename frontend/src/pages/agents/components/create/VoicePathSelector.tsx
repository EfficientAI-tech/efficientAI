import { Phone, Cloud } from 'lucide-react'
import type { CreateAgentPath } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'
import { WIZARD_EXISTING_PLATFORM_LABEL } from './wizardCopy'

interface VoicePathSelectorProps {
  value: CreateAgentPath
  onChange: (path: CreateAgentPath) => void
  embedded?: boolean
  compact?: boolean
}

const OPTIONS: { id: CreateAgentPath; label: string; subtitle: string; icon: typeof Phone }[] = [
  { id: 'telephony', label: 'Telephony', subtitle: 'Your phone numbers & SIP', icon: Phone },
  {
    id: 'platform',
    label: WIZARD_EXISTING_PLATFORM_LABEL,
    subtitle: 'Vapi, Retell, ElevenLabs, Smallest',
    icon: Cloud,
  },
]

export default function VoicePathSelector({
  value,
  onChange,
  embedded,
  compact,
}: VoicePathSelectorProps) {
  const active = value === 'chat' ? 'telephony' : value

  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="Voice deployment"
          subtitle="Phone numbers or an agent on Vapi, Retell, ElevenLabs, or Smallest."
          prominence={compact ? 'entry' : 'default'}
        />
      ) : null}
      <div className={`grid grid-cols-2 w-full ${compact ? 'gap-3.5 mt-4' : 'gap-4 mt-6'}`}>
        {OPTIONS.map((option) => (
          <WizardIconCard
            key={option.id}
            label={option.label}
            subtitle={compact ? option.subtitle : undefined}
            icon={option.icon}
            selected={active === option.id}
            onSelect={() => onChange(option.id)}
            large={!compact}
            compact={compact}
          />
        ))}
      </div>
    </div>
  )
}
