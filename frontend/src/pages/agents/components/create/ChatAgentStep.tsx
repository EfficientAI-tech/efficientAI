import type { CreateAgentFormData } from './createAgentTypes'
import { CREATE_WIZARD_FIELD_CLASS, CREATE_WIZARD_LABEL_CLASS } from './createWizardUi'

interface ChatAgentStepProps {
  formData: CreateAgentFormData
  productionPrompt: string
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  onProductionPromptChange: (value: string) => void
  showProductionPrompt?: boolean
  compact?: boolean
}

export function validateChatAgentStep(formData: CreateAgentFormData, productionPrompt: string): boolean {
  return Boolean(formData.name.trim() && productionPrompt.trim())
}

export default function ChatAgentStep({
  formData,
  productionPrompt,
  onFormChange,
  onProductionPromptChange,
  showProductionPrompt = true,
  compact = false,
}: ChatAgentStepProps) {
  return (
    <div className="w-full space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_7.5rem] gap-3 items-end">
        <div className="min-w-0">
          <label className={CREATE_WIZARD_LABEL_CLASS}>Name *</label>
          <input
            type="text"
            required
            className={CREATE_WIZARD_FIELD_CLASS}
            value={formData.name}
            onChange={(e) => onFormChange({ name: e.target.value })}
            placeholder="Customer Support Bot"
          />
        </div>
        <div className="min-w-0">
          <label className={CREATE_WIZARD_LABEL_CLASS}>Language</label>
          <select
            className={CREATE_WIZARD_FIELD_CLASS}
            value={formData.language}
            onChange={(e) => onFormChange({ language: e.target.value })}
          >
            <option value="en">English</option>
            <option value="hi">Hindi</option>
            <option value="es">Spanish</option>
            <option value="fr">French</option>
            <option value="de">German</option>
          </select>
        </div>
      </div>
      {showProductionPrompt ? (
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Production prompt *</label>
          <textarea
            className={`${CREATE_WIZARD_FIELD_CLASS} font-mono text-xs resize-y ${
              compact ? 'min-h-[112px]' : 'min-h-[200px]'
            }`}
            value={productionPrompt}
            onChange={(e) => onProductionPromptChange(e.target.value)}
            placeholder="You are a helpful assistant…"
            rows={compact ? 5 : 8}
          />
        </div>
      ) : null}
    </div>
  )
}
