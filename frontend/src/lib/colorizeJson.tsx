import type { ReactNode } from 'react'

export function colorizeJson(source: string): ReactNode[] {
  const tokenRe =
    /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(?:\s*:)?|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:])/g
  const nodes: ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = tokenRe.exec(source))) {
    if (match.index > last) {
      nodes.push(
        <span key={key++} className="text-slate-400">
          {source.slice(last, match.index)}
        </span>,
      )
    }
    const token = match[0]
    let className = 'text-slate-300'
    if (
      token === '{' ||
      token === '}' ||
      token === '[' ||
      token === ']' ||
      token === ',' ||
      token === ':'
    ) {
      className = 'text-slate-500'
    } else if (token === 'true' || token === 'false' || token === 'null') {
      className = 'text-violet-300'
    } else if (!Number.isNaN(Number(token))) {
      className = 'text-amber-300'
    } else if (token.endsWith(':')) {
      className = 'text-sky-300'
    } else {
      className = 'text-emerald-300'
    }
    nodes.push(
      <span key={key++} className={className}>
        {token}
      </span>,
    )
    last = match.index + token.length
  }
  if (last < source.length) {
    nodes.push(
      <span key={key++} className="text-slate-400">
        {source.slice(last)}
      </span>,
    )
  }
  return nodes
}
