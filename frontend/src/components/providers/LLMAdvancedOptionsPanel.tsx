import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import {
  getVisibleLLMParams,
  isLLMGenerationConfigEmpty,
  normalizeLLMConfig,
  summarizeLLMConfig,
  type LLMGenerationConfig,
  type LLMGenerationParamKey,
} from '../../config/llmGenerationParams'

interface LLMAdvancedOptionsPanelProps {
  provider: string | null | undefined
  value: LLMGenerationConfig | null | undefined
  onChange: (next: LLMGenerationConfig | null) => void
  disabled?: boolean
  /** When true, show Gemini thinking note. */
  showGeminiNote?: boolean
  className?: string
}

export default function LLMAdvancedOptionsPanel({
  provider,
  value,
  onChange,
  disabled = false,
  showGeminiNote = true,
  className,
}: LLMAdvancedOptionsPanelProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const params = getVisibleLLMParams(provider)
  const summary = summarizeLLMConfig(value)
  const providerKey = (provider || '').toLowerCase()

  const handleFieldChange = (key: LLMGenerationParamKey, raw: string) => {
    const next: LLMGenerationConfig = { ...(value || {}) }
    if (raw === '' || raw === undefined) {
      delete next[key]
    } else {
      const meta = params.find((p) => p.key === key)
      next[key] = meta?.integer ? parseInt(raw, 10) : parseFloat(raw)
    }
    onChange(normalizeLLMConfig(next))
  }

  const handleReset = () => {
    onChange(null)
  }

  if (!provider) {
    return null
  }

  return (
    <div className={`border border-gray-200 rounded-lg overflow-hidden ${className ?? ''}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-500 hover:text-gray-700 bg-gray-50 transition-colors disabled:opacity-50"
      >
        <span className="flex items-center gap-1.5">
          <svg
            className="w-3.5 h-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v6m0 6v6m8.66-15l-5.2 3m-6.92 4l-5.2 3M22.66 18l-5.2-3m-6.92-4l-5.2-3" />
          </svg>
          Advanced Options
          {summary && (
            <span className="ml-1 text-[10px] px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded-full">
              {summary}
            </span>
          )}
        </span>
        {showAdvanced ? (
          <ChevronUp className="w-3.5 h-3.5" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5" />
        )}
      </button>
      {showAdvanced && (
        <div className="px-3 py-3 bg-gray-50/50 border-t border-gray-200 space-y-3">
          {showGeminiNote && providerKey === 'google' && (
            <p className="text-[10px] text-gray-500">
              Gemini thinking level is managed automatically for structured evaluation tasks.
            </p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {params.map((param) => (
              <div key={param.key}>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  {param.label}
                </label>
                <input
                  type="number"
                  disabled={disabled}
                  min={param.min}
                  max={param.max}
                  step={param.step ?? (param.integer ? 1 : 0.1)}
                  value={value?.[param.key] ?? ''}
                  placeholder={param.placeholder ?? 'Default'}
                  onChange={(e) => handleFieldChange(param.key, e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50"
                />
                {param.helpText && (
                  <p className="mt-1 text-[10px] text-gray-400">{param.helpText}</p>
                )}
              </div>
            ))}
          </div>
          {!isLLMGenerationConfigEmpty(value) && (
            <button
              type="button"
              disabled={disabled}
              onClick={handleReset}
              className="text-xs text-gray-500 hover:text-gray-700 underline"
            >
              Reset to defaults
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export type { LLMGenerationConfig }
