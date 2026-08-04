import ReactMarkdown from 'react-markdown'
import { SCENARIO_MARKDOWN_PROSE, SCENARIO_MARKDOWN_PROSE_LG } from './scenarioMarkdown'

interface ScenarioMarkdownViewProps {
  content: string
  className?: string
  emptyMessage?: string
  size?: 'sm' | 'lg'
}

export default function ScenarioMarkdownView({
  content,
  className = '',
  emptyMessage,
  size = 'sm',
}: ScenarioMarkdownViewProps) {
  if (!content.trim()) {
    return emptyMessage ? (
      <p className="text-sm text-gray-400 italic">{emptyMessage}</p>
    ) : null
  }

  const proseClass = size === 'lg' ? SCENARIO_MARKDOWN_PROSE_LG : SCENARIO_MARKDOWN_PROSE

  return (
    <div className={`${proseClass} ${className}`}>
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
