import { ChevronRight, Mic, Trash2 } from 'lucide-react'
import ProviderLogo, { getProviderInfo } from '../../components/shared/ProviderLogo'
import type { Persona } from './personaTypes'

interface PersonaTileProps {
  persona: Persona
  onClick: (persona: Persona) => void
  onDelete: (persona: Persona) => void
}

function truncate(text: string, maxLen: number): string {
  const trimmed = text.trim()
  if (trimmed.length <= maxLen) return trimmed
  return `${trimmed.slice(0, maxLen).trim()}…`
}

function behaviorSummary(persona: Persona): string | null {
  const parts: string[] = []
  if (persona.llm_temperature != null) {
    parts.push(`Temp ${persona.llm_temperature}`)
  }
  if (persona.max_turns != null) {
    parts.push(`${persona.max_turns} turns`)
  }
  if (persona.response_delay_ms != null) {
    parts.push(`${persona.response_delay_ms}ms delay`)
  }
  if (persona.allow_interruptions != null) {
    parts.push(persona.allow_interruptions ? 'Interrupts' : 'No interrupts')
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

export default function PersonaTile({ persona, onClick, onDelete }: PersonaTileProps) {
  const providerInfo = persona.tts_provider ? getProviderInfo(persona.tts_provider) : null
  const promptPreview = persona.description?.trim()
  const behavior = behaviorSummary(persona)

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onClick(persona)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(persona)
        }
      }}
      className="group bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md hover:border-primary-200 transition-all cursor-pointer overflow-hidden"
    >
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-gray-900 truncate group-hover:text-primary-700 transition-colors">
              {persona.name}
            </h3>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              {persona.tts_provider ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-gray-50 border border-gray-200 text-xs text-gray-700">
                  <ProviderLogo provider={persona.tts_provider} size="sm" />
                  {providerInfo?.label || persona.tts_provider}
                </span>
              ) : (
                <span className="text-xs text-gray-400">No TTS provider</span>
              )}
              {persona.tts_voice_name ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-50 text-xs text-primary-700">
                  <Mic className="h-3 w-3" />
                  {persona.tts_voice_name}
                </span>
              ) : null}
              <span className="inline-flex px-2 py-0.5 rounded-full bg-gray-100 text-xs text-gray-600 capitalize">
                {persona.gender}
              </span>
              {persona.is_custom ? (
                <span className="px-1.5 py-0.5 text-[10px] font-medium bg-amber-100 text-amber-700 rounded">
                  Custom voice
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(persona)
              }}
              className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
              title="Delete persona"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <ChevronRight className="h-5 w-5 text-gray-300 group-hover:text-primary-400 transition-colors" />
          </div>
        </div>

        {promptPreview ? (
          <p className="mt-3 text-sm text-gray-600 line-clamp-2 leading-relaxed">
            {truncate(promptPreview, 140)}
          </p>
        ) : (
          <p className="mt-3 text-sm text-gray-400 italic">No persona prompt configured</p>
        )}

        {behavior ? (
          <p className="mt-2 text-xs text-gray-500">{behavior}</p>
        ) : null}
      </div>

      <div className="px-5 py-2.5 border-t border-gray-100 bg-gray-50/60 text-xs text-gray-500 group-hover:text-primary-600 transition-colors">
        Click to edit prompt, voice, TTS, behavior, and environment
      </div>
    </article>
  )
}
