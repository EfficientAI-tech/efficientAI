import { diffLines } from 'diff'

function splitChunk(value: string): string[] {
  const trimmed = value.endsWith('\n') ? value.slice(0, -1) : value
  if (!trimmed) return []
  return trimmed.split('\n')
}

function withContext(lines: string[], edge = 3): string[] {
  if (lines.length <= edge * 2 + 1) return lines
  return [...lines.slice(0, edge), '…', ...lines.slice(-edge)]
}

export default function PromptLineDiff({
  before,
  after,
}: {
  before: string
  after: string
}) {
  if (!before) {
    return (
      <pre className="overflow-x-auto rounded border border-emerald-200 bg-emerald-50 text-xs font-mono leading-5">
        {splitChunk(after).map((line, index) => (
          <div key={index} className="px-2 text-emerald-900">
            <span className="select-none text-emerald-600">+ </span>
            {line || ' '}
          </div>
        ))}
      </pre>
    )
  }

  const parts = diffLines(before, after)
  return (
    <pre className="overflow-x-auto rounded border border-gray-200 bg-white text-xs font-mono leading-5">
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
  )
}
