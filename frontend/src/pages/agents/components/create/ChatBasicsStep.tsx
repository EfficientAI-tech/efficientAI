import { MODERN_INPUT_CLASS, MODERN_SELECT_CLASS } from '../../../evaluators/components/evaluatorUi'
import type { CreateAgentFormData } from './createAgentTypes'

interface ChatBasicsStepProps {
  formData: CreateAgentFormData
  onChange: (patch: Partial<CreateAgentFormData>) => void
}

export function validateChatBasics(formData: CreateAgentFormData): boolean {
  return Boolean(formData.name.trim())
}

export default function ChatBasicsStep({ formData, onChange }: ChatBasicsStepProps) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Text chat agent for LLM-to-LLM pre-prod. Next: production prompt, then connection layer
        (which LLM runs your main agent vs the simulated customer).
      </p>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Agent name</label>
        <input
          className={MODERN_INPUT_CLASS}
          value={formData.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="e.g. MoneyView collections chat"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Language</label>
        <select
          className={MODERN_SELECT_CLASS}
          value={formData.language}
          onChange={(e) => onChange({ language: e.target.value })}
        >
          <option value="en">English</option>
          <option value="hi">Hindi</option>
          <option value="es">Spanish</option>
        </select>
      </div>
    </div>
  )
}
