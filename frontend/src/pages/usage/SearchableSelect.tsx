import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search, X } from 'lucide-react'
import { usageTheme } from './usageTheme'

export type SearchableOption = { id: string; label: string }

type SearchableSelectProps = {
  label: string
  placeholder: string
  value: string
  options: SearchableOption[]
  onChange: (id: string) => void
  disabled?: boolean
  emptyMessage?: string
}

export default function SearchableSelect({
  label,
  placeholder,
  value,
  options,
  onChange,
  disabled,
  emptyMessage = 'No matches',
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  const selected = options.find((o) => o.id === value)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q))
  }, [options, search])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  return (
    <div ref={rootRef} className="relative min-w-0">
      <span className="text-xs font-medium text-gray-500">{label}</span>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`mt-1 flex w-full items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-900 shadow-sm transition-colors hover:border-[#facc15] focus:outline-none disabled:opacity-50 ${usageTheme.focusRing}`}
      >
        <span className="flex-1 truncate">
          {selected ? selected.label : placeholder}
        </span>
        {value ? (
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

      {open && !disabled ? (
        <div className="absolute z-30 mt-1 w-full min-w-[16rem] rounded-lg border border-[#fde047]/60 bg-white shadow-lg ring-1 ring-[#fef9c3]/50">
          <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…"
              className="flex-1 text-sm outline-none"
              autoFocus
            />
          </div>
          <ul className="max-h-56 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-sm text-gray-500">{emptyMessage}</li>
            ) : (
              filtered.map((opt) => (
                <li key={opt.id}>
                  <button
                    type="button"
                    className={`w-full px-3 py-2 text-left text-sm hover:bg-[#fefce8] ${
                      opt.id === value
                        ? usageTheme.selectHighlight
                        : 'text-gray-800'
                    }`}
                    onClick={() => {
                      onChange(opt.id)
                      setOpen(false)
                      setSearch('')
                    }}
                  >
                    {opt.label}
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
