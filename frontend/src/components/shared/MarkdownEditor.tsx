import { useState } from 'react'
import { Code, Eye } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
  minWords?: number
  required?: boolean
}

export default function MarkdownEditor({
  value,
  onChange,
  placeholder = 'Enter content... Markdown is supported',
  rows = 6,
  minWords,
  required = false,
}: MarkdownEditorProps) {
  const [mode, setMode] = useState<'write' | 'preview'>('write')
  
  const wordCount = value.trim().split(/\s+/).filter(Boolean).length
  const meetsMinWords = !minWords || wordCount >= minWords
  
  return (
    <div>
      <div className="flex items-center justify-end mb-1">
        <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => setMode('write')}
            className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              mode === 'write'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Code className="h-3 w-3" />
            Write
          </button>
          <button
            type="button"
            onClick={() => setMode('preview')}
            className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              mode === 'preview'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Eye className="h-3 w-3" />
            Preview
          </button>
        </div>
      </div>

      {mode === 'write' ? (
        <textarea
          required={required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
          rows={rows}
          placeholder={placeholder}
        />
      ) : (
        <div className="min-h-[150px] max-h-[300px] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100">
          {value ? (
            <ReactMarkdown>{value}</ReactMarkdown>
          ) : (
            <p className="text-gray-400 italic">Nothing to preview yet...</p>
          )}
        </div>
      )}
      
      {minWords && (
        <p className={`mt-1 text-xs ${meetsMinWords ? 'text-green-600' : 'text-gray-500'}`}>
          {wordCount}/{minWords} words minimum
        </p>
      )}
    </div>
  )
}
