import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown } from 'lucide-react'
import { useAnchoredMenuPosition } from '../../hooks/useAnchoredMenuPosition'
import { MODERN_SELECT_CLASS } from '../../pages/evaluators/components/evaluatorUi'

export type AnchoredSelectOption = {
  value: string
  label: string
  iconUrl?: string | null
}

type Props = {
  id?: string
  label: string
  labelSuffix?: ReactNode
  value: string
  options: AnchoredSelectOption[]
  onChange: (value: string) => void
  disabled?: boolean
  placeholder?: string
  maxMenuHeight?: number
}

function eventInside(node: HTMLElement | null, event: MouseEvent): boolean {
  if (!node) return false
  const target = event.target
  if (target instanceof Node && node.contains(target)) return true
  return event.composedPath().includes(node)
}

export default function AnchoredSelect({
  id: idProp,
  label,
  labelSuffix,
  value,
  options,
  onChange,
  disabled,
  placeholder = 'Select…',
  maxMenuHeight,
}: Props) {
  const autoId = useId()
  const id = idProp ?? autoId
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const anchorRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const position = useAnchoredMenuPosition(open && !disabled, anchorRef, {
    maxHeight: maxMenuHeight,
  })

  const selected = options.find((o) => o.value === value)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (eventInside(rootRef.current, e) || eventInside(panelRef.current, e)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div ref={rootRef} className="min-w-0">
      <div className="mb-1.5 flex items-center gap-1.5">
        <label htmlFor={id} className="text-xs font-medium text-gray-700">
          {label}
        </label>
        {labelSuffix}
      </div>
      <button
        id={id}
        ref={anchorRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`${MODERN_SELECT_CLASS} flex items-center justify-between gap-2 text-left disabled:bg-gray-50 disabled:text-gray-400`}
      >
        <span className={`flex items-center gap-2 min-w-0 truncate ${selected ? 'text-gray-900' : 'text-gray-400'}`}>
          {selected?.iconUrl ? (
            <img src={selected.iconUrl} alt="" className="h-4 w-4 shrink-0 object-contain" />
          ) : null}
          <span className="truncate">{selected?.label ?? placeholder}</span>
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && !disabled && position && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={panelRef}
              role="listbox"
              className="overflow-y-auto overscroll-contain rounded-lg border border-gray-200 bg-white py-1 shadow-lg ring-1 ring-black/5"
              style={position.style}
              onMouseDown={(e) => e.stopPropagation()}
            >
              {options.map((opt) => (
                <button
                  key={opt.value || '__empty__'}
                  type="button"
                  role="option"
                  aria-selected={opt.value === value}
                  className={`w-full px-3 py-2.5 text-left text-sm hover:bg-gray-50 ${
                    opt.value === value ? 'bg-primary-50 text-primary-900 font-medium' : 'text-gray-800'
                  }`}
                  onClick={() => {
                    onChange(opt.value)
                    setOpen(false)
                  }}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    {opt.iconUrl ? (
                      <img src={opt.iconUrl} alt="" className="h-4 w-4 shrink-0 object-contain" />
                    ) : null}
                    <span className="truncate">{opt.label}</span>
                  </span>
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
