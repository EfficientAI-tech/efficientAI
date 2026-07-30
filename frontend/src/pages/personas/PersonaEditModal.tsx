import { useEffect, useMemo, useState } from 'react'
import { Save, X } from 'lucide-react'
import Button from '../../components/Button'
import PersonaTabContent from './PersonaTabContent'
import {
  PERSONA_TILE_TABS,
  personaToFormData,
  type Persona,
  type PersonaFormData,
  type PersonaTileTab,
  type ProviderOption,
  formDataEquals,
} from './personaTypes'

interface PersonaEditModalProps {
  persona: Persona
  providers: ProviderOption[]
  isSaving?: boolean
  onSave: (id: string, data: PersonaFormData) => void
  onClose: () => void
}

export default function PersonaEditModal({
  persona,
  providers,
  isSaving = false,
  onSave,
  onClose,
}: PersonaEditModalProps) {
  const [activeTab, setActiveTab] = useState<PersonaTileTab>('prompt')
  const [draft, setDraft] = useState<PersonaFormData>(() => personaToFormData(persona))

  useEffect(() => {
    setDraft(personaToFormData(persona))
    setActiveTab('prompt')
  }, [persona.id, persona.updated_at])

  const baseline = useMemo(() => personaToFormData(persona), [persona])
  const isDirty = !formDataEquals(draft, baseline)
  const lockProvider = Boolean(persona.tts_provider)

  const handleClose = () => {
    if (isDirty && !window.confirm('Discard unsaved changes?')) {
      return
    }
    onClose()
  }

  const handleSave = () => {
    onSave(persona.id, draft)
  }

  const handleDiscard = () => {
    setDraft(baseline)
  }

  return (
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
      <div
        className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center gap-4">
          <div className="min-w-0 flex-1">
            <h3 className="text-lg font-semibold text-gray-900">Edit Persona</h3>
            <input
              type="text"
              value={draft.name}
              onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
              className="mt-1 w-full text-sm text-gray-700 bg-transparent border-0 border-b border-transparent hover:border-gray-200 focus:border-primary-400 focus:ring-0 px-0 py-0.5"
              aria-label="Persona name"
              placeholder="Persona name"
            />
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 shrink-0"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 border-b border-gray-100">
          <nav className="flex gap-1 overflow-x-auto" aria-label="Persona settings">
            {PERSONA_TILE_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`whitespace-nowrap px-3 py-2 text-xs font-medium rounded-t-lg border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? 'border-primary-500 text-primary-700 bg-primary-50/60'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-6 overflow-y-auto flex-1 min-h-[320px]">
          <PersonaTabContent
            tab={activeTab}
            draft={draft}
            onChange={setDraft}
            providers={providers}
            lockProvider={lockProvider}
            voiceFieldSize="md"
            promptEmbedded
          />
        </div>

        <div className="px-6 py-4 border-t border-gray-200 bg-gray-50/50 flex items-center justify-between gap-3">
          <span className="text-xs text-gray-500">
            {isDirty ? 'Unsaved changes' : 'All changes saved'}
          </span>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={isSaving}>
              Cancel
            </Button>
            {isDirty ? (
              <Button type="button" variant="ghost" onClick={handleDiscard} disabled={isSaving}>
                Discard
              </Button>
            ) : null}
            <Button
              type="button"
              variant="primary"
              onClick={handleSave}
              isLoading={isSaving}
              disabled={!isDirty || !draft.name.trim() || isSaving}
              leftIcon={!isSaving ? <Save className="h-4 w-4" /> : undefined}
            >
              Save
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
