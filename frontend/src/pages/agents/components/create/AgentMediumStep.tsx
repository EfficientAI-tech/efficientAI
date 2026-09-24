import { Mic, MessagesSquare } from 'lucide-react'
import type { AgentMedium } from './createAgentTypes'
import { WizardStepHeader } from './WizardStepHeader'

interface AgentMediumStepProps {
  value: AgentMedium | null
  onChange: (medium: AgentMedium) => void
}

const OPTIONS: {
  id: AgentMedium
  label: string
  description: string
  icon: typeof Mic
}[] = [
  {
    id: 'voice',
    label: 'Voice agent',
    description: 'Phone calls, web calls, or a connected voice platform (Vapi, Retell, and others).',
    icon: Mic,
  },
  {
    id: 'chat',
    label: 'Text chat agent',
    description: 'LLM simulation, live provider chat, customer HTTP APIs, or messaging channels.',
    icon: MessagesSquare,
  },
]

export default function AgentMediumStep({ value, onChange }: AgentMediumStepProps) {
  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      <WizardStepHeader
        title="What kind of agent do you want to test?"
        subtitle="Pick the medium your production agent uses. You can configure integrations and eval settings in the next steps."
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
