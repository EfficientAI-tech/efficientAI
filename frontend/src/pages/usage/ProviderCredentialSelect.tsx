import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Brain, ChevronDown, Info } from 'lucide-react'
import { getProviderLabel, getProviderLogo } from '../../config/providers'
import type { AIProvider, ModelProvider } from '../../types/api'
import { usageTheme } from './usageTheme'
import { credentialDisplayLabel } from './pricingModelOptions'
import { useAnchoredDropdown } from './useAnchoredDropdown'
function FieldHint({ title, children }: { title: string; children: ReactNode }) {
  return (
    <span className="relative inline-flex group">
      <Info
        className="h-3.5 w-3.5 cursor-help text-gray-400 hover:text-gray-600"
        aria-label={title}
      />
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-30 mt-1.5 hidden w-64 rounded-lg border border-gray-200 bg-white p-2.5 text-xs font-normal leading-relaxed text-gray-600 shadow-lg group-hover:block group-focus-within:block"
      >
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-gray-900">
          {title}
        </span>
        <span className="mt-1 block">{children}</span>
      </span>
    </span>
  )
}

function ProviderLogo({
  provider,
  size = 'sm',
}: {
  provider: ModelProvider
  size?: 'sm' | 'md'
}) {
  const logo = getProviderLogo(provider)
  const label = getProviderLabel(provider)

  if (logo) {
    if (size === 'md') {
      return (
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-gray-200 bg-white p-1.5">
          <img src={logo} alt={label} className="h-full w-full object-contain" />
        </span>
      )
    }
    return <img src={logo} alt={label} className="h-5 w-5 shrink-0 object-contain" />
  }

  if (size === 'md') {
    return (
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-gray-200 bg-white">
        <Brain className="h-5 w-5 text-primary-600" />
      </span>
    )
  }

  return <Brain className="h-5 w-5 shrink-0 text-primary-600" />
}

type Props = {
  label: string
  hint?: string
  value: string
  credentials: AIProvider[]
  onChange: (credentialId: string) => void
  disabled?: boolean
  placeholder?: string
}

export default function ProviderCredentialSelect({
  label,
  hint,
  value,
  credentials,
  onChange,
  disabled,
  placeholder = 'Select integration…',
}: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const anchorRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const coords = useAnchoredDropdown(open && !disabled, anchorRef)
  const selected = credentials.find((row) => row.id === value)

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  return (
    <div ref={rootRef} className="relative min-w-0">
      <div className="flex items-center gap-1.5">
        <span className="text-xs font-medium text-gray-500">{label}</span>
        {hint ? <FieldHint title={label}>{hint}</FieldHint> : null}
      </div>
      <button
        ref={anchorRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}        className={`mt-1 flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-gray-200 bg-white px-3 text-left text-sm text-gray-900 shadow-sm transition-colors hover:border-gray-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${usageTheme.focusRing}`}
      >
        <span className="flex min-w-0 items-center gap-2">
          {selected ? (
            <>
              <ProviderLogo provider={selected.provider} />
              <span className="truncate">{credentialDisplayLabel(selected)}</span>
            </>
          ) : (
            <span className="text-gray-500">{placeholder}</span>
          )}
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && !disabled && coords && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={panelRef}
              className="max-h-60 overflow-y-auto overscroll-contain rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
              style={{
                position: 'fixed',
                top: coords.top,
                left: coords.left,
                width: coords.width,
                zIndex: 60,
              }}
            >
              {credentials.length === 0 ? (
                <p className="px-3 py-2 text-sm text-gray-500">No active integrations</p>
              ) : (
                credentials.map((credential) => {
                  const isSelected = credential.id === value
                  const name = credential.name?.trim()
                  return (
                    <button
                      key={credential.id}
                      type="button"
                      onClick={() => {
                        onChange(credential.id)
                        setOpen(false)
                      }}
                      className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-gray-50 ${
                        isSelected ? 'bg-[#fefce8]' : ''
                      }`}
                    >
                      <ProviderLogo provider={credential.provider} size="md" />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-gray-900">
                          {getProviderLabel(credential.provider)}
                        </span>
                        {name ? (
                          <span className="block truncate text-xs text-gray-500">{name}</span>
                        ) : null}
                      </span>
                    </button>
                  )
                })
              )}
            </div>,
            document.body,
          )
        : null}    </div>
  )
}
