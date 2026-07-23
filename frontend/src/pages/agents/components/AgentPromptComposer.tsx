import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import {
  mergeAgentPromptVariables,
  variablePlaceholder,
  type AgentPromptVariableDef,
} from './agentPromptVariables'

type TriggerKind = 'brace' | 'at'

type MenuItem =
  | { kind: 'variable'; variable: AgentPromptVariableDef }
  | { kind: 'partial'; id: string; name: string; description?: string | null }

interface AgentPromptComposerProps {
  value: string
  onChange: (value: string) => void
  customVariables?: Record<string, string> | null
  rows?: number
  className?: string
  placeholder?: string
}

export default function AgentPromptComposer({
  value,
  onChange,
  customVariables,
  rows = 18,
  className = '',
  placeholder = 'Write your agent description here... Markdown is supported.',
}: AgentPromptComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [triggerKind, setTriggerKind] = useState<TriggerKind>('brace')
  const [triggerIndex, setTriggerIndex] = useState(0)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)

  const variables = useMemo(
    () => mergeAgentPromptVariables(customVariables),
    [customVariables]
  )

  const partialSearch = triggerKind === 'at' ? query : ''
  const { data: partials = [], isLoading: partialsLoading } = useQuery({
    queryKey: ['agent-prompt-composer-partials', partialSearch],
    queryFn: () => apiClient.listPromptPartials(0, 50, partialSearch.trim() || undefined),
    enabled: menuOpen && triggerKind === 'at',
    staleTime: 30_000,
  })

  const filteredVariables = useMemo(() => {
    const q = query.toLowerCase()
    if (!q) return variables
    return variables.filter(
      (v) =>
        v.key.toLowerCase().includes(q) ||
        v.label.toLowerCase().includes(q) ||
        (v.description || '').toLowerCase().includes(q)
    )
  }, [variables, query])

  const partialRows = useMemo(() => {
    if (triggerKind !== 'at') return []
    return (partials as { id: string; name: string; description?: string | null }[]).filter((p) => {
      const q = query.toLowerCase()
      if (!q) return true
      return (
        p.name.toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q)
      )
    })
  }, [partials, query, triggerKind])

  const menuItems: MenuItem[] = useMemo(() => {
    if (triggerKind === 'brace') {
      return filteredVariables.map((variable) => ({ kind: 'variable' as const, variable }))
    }
    const partialItems: MenuItem[] = partialRows.map((p) => ({
      kind: 'partial' as const,
      id: p.id,
      name: p.name,
      description: p.description,
    }))
    const variableItems: MenuItem[] = filteredVariables.map((variable) => ({
      kind: 'variable' as const,
      variable,
    }))
    return [...partialItems, ...variableItems]
  }, [triggerKind, filteredVariables, partialRows])

  useEffect(() => {
    setSelectedIndex(0)
  }, [query, triggerKind, menuItems.length])

  const closeMenu = useCallback(() => {
    setMenuOpen(false)
    setQuery('')
    setSelectedIndex(0)
  }, [])

  const openMenuAt = useCallback((kind: TriggerKind, index: number) => {
    setTriggerKind(kind)
    setTriggerIndex(index)
    setMenuOpen(true)
    setQuery('')
    setSelectedIndex(0)
  }, [])

  const syncMenuFromCursor = useCallback(
    (text: string, cursor: number) => {
      if (cursor <= 0) {
        closeMenu()
        return
      }
      const prev = text[cursor - 1]
      if (prev === '{' || prev === '@') {
        const kind: TriggerKind = prev === '{' ? 'brace' : 'at'
        openMenuAt(kind, cursor - 1)
        setQuery('')
        return
      }
      if (!menuOpen) return
      const ch = text[triggerIndex]
      if (ch !== '{' && ch !== '@') {
        closeMenu()
        return
      }
      if (cursor <= triggerIndex) {
        closeMenu()
        return
      }
      const slice = text.slice(triggerIndex + 1, cursor)
      if (slice.includes('\n') || slice.includes(' ') || (ch === '{' && slice.includes('}'))) {
        closeMenu()
        return
      }
      setQuery(slice)
    },
    [closeMenu, menuOpen, openMenuAt, triggerIndex]
  )

  const applyInsert = useCallback(
    (insertion: string) => {
      const el = textareaRef.current
      if (!el) return
      const cursor = el.selectionStart
      const before = value.slice(0, triggerIndex)
      const after = value.slice(cursor)
      const next = before + insertion + after
      onChange(next)
      closeMenu()
      const newPos = before.length + insertion.length
      requestAnimationFrame(() => {
        el.focus()
        el.setSelectionRange(newPos, newPos)
      })
    },
    [closeMenu, onChange, triggerIndex, value]
  )

  const selectItem = useCallback(
    async (item: MenuItem) => {
      if (item.kind === 'variable') {
        applyInsert(variablePlaceholder(item.variable.key))
        return
      }
      try {
        const detail = await apiClient.getPromptPartial(item.id)
        const content = (detail?.content || '').trim()
        if (!content) return
        applyInsert(content)
      } catch {
        /* ignore */
      }
    },
    [applyInsert]
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!menuOpen || menuItems.length === 0) {
      if (e.key === 'Escape') closeMenu()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((i) => (i + 1) % menuItems.length)
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((i) => (i - 1 + menuItems.length) % menuItems.length)
      return
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      void selectItem(menuItems[selectedIndex])
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      closeMenu()
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value
    onChange(next)
    syncMenuFromCursor(next, e.target.selectionStart)
  }

  const handleClick = () => {
    const el = textareaRef.current
    if (!el) return
    syncMenuFromCursor(value, el.selectionStart)
  }

  const renderMenuItem = (item: MenuItem, idx: number) => {
    if (item.kind === 'partial') {
      return (
        <button
          key={`partial-${item.id}`}
          type="button"
          className={`w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-primary-50 ${
            idx === selectedIndex ? 'bg-primary-50' : ''
          }`}
          onMouseDown={(ev) => {
            ev.preventDefault()
            void selectItem(item)
          }}
        >
          <div className="font-medium text-gray-900">{item.name}</div>
          {item.description ? (
            <div className="text-xs text-gray-500 line-clamp-1">{item.description}</div>
          ) : null}
        </button>
      )
    }
    return (
      <button
        key={`var-${item.variable.key}`}
        type="button"
        className={`w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-primary-50 ${
          idx === selectedIndex ? 'bg-primary-50' : ''
        }`}
        onMouseDown={(ev) => {
          ev.preventDefault()
          void selectItem(item)
        }}
      >
        <div className="font-medium text-gray-900 font-mono text-xs">
          {variablePlaceholder(item.variable.key)}
          {item.variable.builtin ? (
            <span className="ml-2 text-[10px] font-sans text-gray-400">built-in</span>
          ) : null}
        </div>
        {item.variable.description ? (
          <div className="text-xs text-gray-500 line-clamp-1">{item.variable.description}</div>
        ) : null}
      </button>
    )
  }

  const partialCount = menuItems.filter((m) => m.kind === 'partial').length
  const variableCount = menuItems.filter((m) => m.kind === 'variable').length

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onClick={handleClick}
        className={
          className ||
          'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm min-h-[380px]'
        }
        rows={rows}
        placeholder={placeholder}
      />
      <p className="mt-1.5 text-xs text-gray-500">
        Type <code className="text-gray-700">{'{'}</code> for variables,{' '}
        <code className="text-gray-700">@</code> for prompt partials or variables.
      </p>

      {menuOpen && (
        <div
          className="absolute z-20 left-2 right-2 mt-1 max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg text-sm"
          role="listbox"
        >
          {menuItems.length === 0 ? (
            <div className="px-3 py-2 text-gray-500">
              {triggerKind === 'at' && partialsLoading ? 'Loading partials…' : 'No matches'}
            </div>
          ) : (
            <>
              {triggerKind === 'at' && partialCount > 0 && (
                <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400 bg-gray-50 border-b border-gray-100">
                  Prompt partials
                </div>
              )}
              {menuItems.map((item, idx) => {
                const showVarHeader =
                  triggerKind === 'at' &&
                  item.kind === 'variable' &&
                  idx > 0 &&
                  menuItems[idx - 1]?.kind === 'partial'
                return (
                  <div key={item.kind === 'partial' ? `p-${item.id}` : `v-${item.variable.key}`}>
                    {showVarHeader && variableCount > 0 ? (
                      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400 bg-gray-50 border-b border-gray-100">
                        Variables
                      </div>
                    ) : null}
                    {triggerKind === 'at' && item.kind === 'variable' && idx === 0 && variableCount > 0 && partialCount === 0 ? (
                      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400 bg-gray-50 border-b border-gray-100">
                        Variables
                      </div>
                    ) : null}
                    {renderMenuItem(item, idx)}
                  </div>
                )
              })}
            </>
          )}
        </div>
      )}
    </div>
  )
}
