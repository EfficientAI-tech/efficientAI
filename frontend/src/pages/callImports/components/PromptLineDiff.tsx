import { useMemo, useState } from 'react'
import { diffLines } from 'diff'

export type PromptDiffView = 'unified' | 'split'

type SplitRow = {
  left: string
  right: string
  kind: 'add' | 'remove' | 'same' | 'skip'
}

function splitChunk(value: string): string[] {
  const trimmed = value.endsWith('\n') ? value.slice(0, -1) : value
  if (!trimmed) return []
  return trimmed.split('\n')
}

function withContext(lines: string[], edge = 3): string[] {
  if (lines.length <= edge * 2 + 1) return lines
  return [...lines.slice(0, edge), '…', ...lines.slice(-edge)]
}

function buildSplitRows(before: string, after: string): SplitRow[] {
  const rows: SplitRow[] = []
  for (const part of diffLines(before, after)) {
    const lines = part.added || part.removed ? splitChunk(part.value) : splitChunk(part.value)
    if (part.added) {
      for (const line of lines) rows.push({ left: '', right: line, kind: 'add' })
    } else if (part.removed) {
      for (const line of lines) rows.push({ left: line, right: '', kind: 'remove' })
    } else {
      for (const line of lines) rows.push({ left: line, right: line, kind: 'same' })
    }
  }
  return rows
}

export function PromptDiffViewToggle({
  view,
  onChange,
}: {
  view: PromptDiffView
  onChange: (next: PromptDiffView) => void
}) {
  return (
    <div className="inline-flex rounded-md border border-gray-200 bg-white p-0.5 text-[11px] font-medium">
      <button
        type="button"
        onClick={() => onChange('split')}
        className={`rounded px-2 py-0.5 ${
          view === 'split' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:text-gray-900'
        }`}
      >
        Side by side
      </button>
      <button
        type="button"
        onClick={() => onChange('unified')}
        className={`rounded px-2 py-0.5 ${
          view === 'unified' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:text-gray-900'
        }`}
      >
        Unified
      </button>
    </div>
  )
}

export default function PromptLineDiff({
  before,
  after,
  leftLabel = 'Before',
  rightLabel = 'After',
  view: controlledView,
  defaultView = 'split',
  showViewToggle = false,
  maxHeightClass = 'max-h-96',
  className = '',
}: {
  before: string
  after: string
  leftLabel?: string
  rightLabel?: string
  view?: PromptDiffView
  defaultView?: PromptDiffView
  showViewToggle?: boolean
  maxHeightClass?: string
  className?: string
}) {
  const [internalView, setInternalView] = useState<PromptDiffView>(defaultView)
  const view = controlledView ?? internalView
  const splitRows = useMemo(() => buildSplitRows(before, after), [before, after])

  const toolbar =
    showViewToggle && controlledView === undefined ? (
      <div className="mb-1.5 flex items-center justify-end">
        <PromptDiffViewToggle view={view} onChange={setInternalView} />
      </div>
    ) : null

  const rootClass = className ? `flex h-full min-h-0 flex-col ${className}` : ''

  if (!before) {
    return (
      <div className={rootClass}>
        {toolbar}
        <div className={`min-h-0 flex-1 overflow-auto rounded border border-gray-200 ${maxHeightClass}`}>
          <div className="grid grid-cols-2 border-b border-gray-200 bg-gray-50 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            <div className="px-2 py-1 border-r border-gray-200">{leftLabel}</div>
            <div className="px-2 py-1">{rightLabel}</div>
          </div>
          <pre className="text-xs font-mono leading-5">
            {splitChunk(after).map((line, index) => (
              <div key={index} className="grid grid-cols-2 border-b border-gray-100">
                <div className="border-r border-gray-100 bg-gray-50/80 px-2 text-gray-300"> </div>
                <div className="bg-emerald-50 px-2 text-emerald-900">{line || ' '}</div>
              </div>
            ))}
          </pre>
        </div>
      </div>
    )
  }

  if (view === 'split') {
    return (
      <div className={rootClass}>
        {toolbar}
        <div className={`min-h-0 flex-1 overflow-auto rounded border border-gray-200 ${maxHeightClass}`}>
          <div className="grid grid-cols-2 border-b border-gray-200 bg-gray-50 text-[10px] font-semibold uppercase tracking-wide text-gray-500 sticky top-0 z-[1]">
            <div className="px-2 py-1 border-r border-gray-200">{leftLabel}</div>
            <div className="px-2 py-1">{rightLabel}</div>
          </div>
          <pre className="text-xs font-mono leading-5">
            {splitRows.map((row, index) => {
              const leftClass =
                row.kind === 'remove'
                  ? 'bg-rose-50 text-rose-900'
                  : row.kind === 'same'
                    ? 'text-gray-700'
                    : 'bg-gray-50/50 text-gray-300'
              const rightClass =
                row.kind === 'add'
                  ? 'bg-emerald-50 text-emerald-900'
                  : row.kind === 'same'
                    ? 'text-gray-700'
                    : 'bg-gray-50/50 text-gray-300'
              return (
                <div key={index} className="grid grid-cols-2 border-b border-gray-100 min-h-[1.25rem]">
                  <div className={`border-r border-gray-100 px-2 whitespace-pre-wrap break-words ${leftClass}`}>
                    {row.left || ' '}
                  </div>
                  <div className={`px-2 whitespace-pre-wrap break-words ${rightClass}`}>
                    {row.right || ' '}
                  </div>
                </div>
              )
            })}
          </pre>
        </div>
      </div>
    )
  }

  const parts = diffLines(before, after)
  return (
    <div className={rootClass}>
      {toolbar}
      <pre
        className={`min-h-0 flex-1 overflow-auto rounded border border-gray-200 bg-white text-xs font-mono leading-5 ${maxHeightClass}`}
      >
        {parts.map((part, partIndex) => {
          const lines = part.added || part.removed ? splitChunk(part.value) : withContext(splitChunk(part.value))
          const prefix = part.added ? '+' : part.removed ? '-' : ' '
          const rowClass = part.added
            ? 'bg-emerald-50 text-emerald-900'
            : part.removed
              ? 'bg-rose-50 text-rose-900'
              : 'text-gray-600'
          const markClass = part.added
            ? 'text-emerald-600'
            : part.removed
              ? 'text-rose-600'
              : 'text-gray-400'
          return lines.map((line, lineIndex) => (
            <div key={`${partIndex}-${lineIndex}`} className={`px-2 ${rowClass}`}>
              <span className={`select-none ${markClass}`}>{line === '…' ? '  ' : `${prefix} `}</span>
              {line || ' '}
            </div>
          ))
        })}
      </pre>
    </div>
  )
}
