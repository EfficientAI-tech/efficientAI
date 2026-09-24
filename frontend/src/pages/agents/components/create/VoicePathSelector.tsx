import { Phone, Link2 } from 'lucide-react'
import type { CreateAgentPath } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'

interface VoicePathSelectorProps {
  value: CreateAgentPath
  onChange: (path: CreateAgentPath) => void
}

const OPTIONS: {
  id: CreateAgentPath
  label: string
  description: string
  icon: typeof Phone
}[] = [
  {
    id: 'telephony',
    label: 'Telephony',
    description: 'Agents on phone numbers with your carrier or SIP setup.',
    icon: Phone,
  },
  {
    id: 'platform',
    label: 'Voice platform',
    description: 'Agents hosted on Vapi, Retell, ElevenLabs, or Smallest.',
    icon: Link2,
  },
]

export default function VoicePathSelector({ value, onChange }: VoicePathSelectorProps) {
  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      <WizardStepHeader
        title="How is your voice agent deployed?"
        subtitle="Telephony uses numbers and call routing; voice platform connects directly to your provider agent."
      />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {OPTIONS.map((option) => {
          const Icon = option.icon
          const isSelected = value === option.id
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => onChange(option.id)}
              className={`text-left rounded-xl border-2 p-4 transition-colors ${
                isSelected
                  ? 'border-primary-600 bg-primary-50 ring-1 ring-primary-200'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                    isSelected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <span
                    className={`text-sm font-semibold block ${
                      isSelected ? 'text-primary-900' : 'text-gray-900'
                    }`}
                  >
                    {option.label}
                  </span>
                  <span className="text-xs text-gray-600 mt-1 block leading-relaxed">
                    {option.description}
                  </span>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
