import { Phone, Link2 } from 'lucide-react'
import type { CreateAgentPath } from './createAgentTypes'

interface CreateAgentPathSelectorProps {
  value: CreateAgentPath
  onChange: (path: CreateAgentPath) => void
}

export default function CreateAgentPathSelector({ value, onChange }: CreateAgentPathSelectorProps) {
  const options: { id: CreateAgentPath; label: string; description: string; icon: typeof Phone }[] = [
    {
      id: 'telephony',
      label: 'Telephony',
      description: 'Phone-based agent with pasted production prompt',
      icon: Phone,
    },
    {
      id: 'platform',
      label: 'Existing Platform Integration',
      description: 'Connect VAPI, Retell, ElevenLabs, or Smallest',
      icon: Link2,
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {options.map((option) => {
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
                : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <Icon className={`h-5 w-5 ${isSelected ? 'text-primary-600' : 'text-gray-500'}`} />
              <span className={`text-sm font-semibold ${isSelected ? 'text-primary-900' : 'text-gray-900'}`}>
                {option.label}
              </span>
            </div>
            <p className="text-xs text-gray-500">{option.description}</p>
          </button>
        )
      })}
    </div>
  )
}
