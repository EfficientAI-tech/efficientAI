import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Info, Search, X } from 'lucide-react'
import { usageTheme } from './usageTheme'
import { useAnchoredDropdown } from './useAnchoredDropdown'
export type SearchableOption = { id: string; label: string }

type SearchableSelectProps = {
  label: string
  placeholder: string
  value: string
  options: SearchableOption[]
  onChange: (id: string) => void
  disabled?: boolean
  emptyMessage?: string
  hint?: string
}

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

export default function SearchableSelect({
  label,
  placeholder,
  value,
  options,
  onChange,
  disabled,
  emptyMessage = 'No matches',
  hint,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const anchorRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const coords = useAnchoredDropdown(open && !disabled, anchorRef)
  const selected = options.find(
    (o) => o.id === value || o.id.toLowerCase() === value.toLowerCase(),
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q))
  }, [options, search])

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
        onClick={() => setOpen((v) => !v)}
        className={`mt-1 flex h-10 w-full items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 text-left text-sm text-gray-900 shadow-sm transition-colors hover:border-[#facc15] focus:outline-none disabled:opacity-50 ${usageTheme.focusRing}`}
      >
        <span className="flex-1 truncate">
          {selected ? selected.label : placeholder}
        </span>        {value ? (
          <span
            role="button"
            tabIndex={0}
            className="shrink-0 rounded p-0.5 text-gray-400 hover:text-gray-600"
            onClick={(e) => {
              e.stopPropagation()
              onChange('')
              setSearch('')
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation()
                onChange('')
                setSearch('')
              }
            }}
          >
            <X className="h-4 w-4" />
          </span>
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
        )}
      </button>

      {open && !disabled && coords && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={panelRef}
              className="rounded-lg border border-[#fde047]/60 bg-white shadow-lg ring-1 ring-[#fef9c3]/50"
              style={{
                position: 'fixed',
                top: coords.top,
                left: coords.left,
                width: coords.width,
                zIndex: 60,
              }}
            >
              <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2">
                <Search className="h-4 w-4 shrink-0 text-gray-400" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search…"
                  className="min-w-0 flex-1 text-sm outline-none"
                  autoFocus
                />
              </div>
              <ul className="max-h-56 overflow-y-auto overscroll-contain py-1">
                {filtered.length === 0 ? (
                  <li className="px-3 py-2 text-sm text-gray-500">{emptyMessage}</li>
                ) : (
                  filtered.map((opt) => (
                    <li key={opt.id}>
                      <button
                        type="button"
                        className={`w-full px-3 py-2 text-left text-sm hover:bg-[#fefce8] ${
                          opt.id === value ||
                          opt.id.toLowerCase() === value.toLowerCase()
                            ? usageTheme.selectHighlight
                            : 'text-gray-800'
                        }`}
                        onClick={() => {
                          onChange(opt.id)
                          setOpen(false)
                          setSearch('')
                        }}
                      >
                        <span className="block break-all leading-snug">{opt.label}</span>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </div>,
            document.body,
          )
        : null}    </div>
  )
}
