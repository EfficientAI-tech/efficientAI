import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'

export interface PromptHighlightRange {
  start: number
  end: number
  excerpt: string
}

export default function AgentPromptSectionView({
  content,
  highlight,
  previewMode,
}: {
  content: string
  highlight: PromptHighlightRange | null
  previewMode: 'preview' | 'raw'
}) {
  const highlightRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!highlight) return
    const handle = setTimeout(() => {
      highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
    return () => clearTimeout(handle)
  }, [highlight?.start, highlight?.end, previewMode])

  if (!highlight || highlight.start == null || highlight.end == null) {
    if (previewMode === 'preview') {
      return (
        <div className="p-6 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      )
    }
    return (
      <div className="p-6">
        <pre className="whitespace-pre-wrap text-sm text-gray-800 font-mono bg-gray-50 rounded-lg p-4 border border-gray-200">
          {content}
        </pre>
      </div>
    )
  }

  const before = content.slice(0, highlight.start)
  const highlighted = content.slice(highlight.start, highlight.end)
  const after = content.slice(highlight.end)

  if (previewMode === 'preview') {
    return (
      <div className="p-6 space-y-4">
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Showing mapped prompt section. Switch to <strong>Raw</strong> for exact position in
          the full prompt.
        </div>
        <div className="rounded-lg border-2 border-amber-300 bg-amber-50/60 p-4 prose prose-sm max-w-none">
          <ReactMarkdown>{highlighted || highlight.excerpt}</ReactMarkdown>
        </div>
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer hover:text-gray-700">View full prompt</summary>
          <div className="mt-3 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
        </details>
      </div>
    )
  }

  return (
    <div className="p-6">
      <pre className="whitespace-pre-wrap text-sm text-gray-800 font-mono bg-gray-50 rounded-lg p-4 border border-gray-200">
        {before}
        <mark
          ref={highlightRef}
          className="bg-amber-200 text-gray-900 rounded-sm px-0.5"
        >
          {highlighted || highlight.excerpt}
        </mark>
        {after}
      </pre>
    </div>
  )
}
