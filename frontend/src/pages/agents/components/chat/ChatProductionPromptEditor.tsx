import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Code, Eye, Loader2, RefreshCw } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { apiClient } from '../../../../lib/api'

const PROSE =
  'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded'

interface ChatProductionPromptEditorProps {
  value: string
  onChange: (value: string) => void
  showImportFromProvider?: boolean
  integrationId?: string
  agentId?: string
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function ChatProductionPromptEditor({
  value,
  onChange,
  showImportFromProvider,
  integrationId,
  agentId,
  showToast,
}: ChatProductionPromptEditorProps) {
  const [mode, setMode] = useState<'write' | 'preview'>('write')

  const fetchPromptMutation = useMutation({
    mutationFn: () => {
      if (!integrationId || !agentId?.trim()) {
        throw new Error('Select integration and agent ID first')
      }
      return apiClient.previewIntegrationAgentPrompt(integrationId, agentId.trim(), {
        agentChannel: 'chat',
      })
    },
    onSuccess: (data: { provider_prompt?: string }) => {
      onChange(data.provider_prompt || '')
      showToast('Prompt imported from provider', 'success')
    },
    onError: (err: unknown) => {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err as Error)?.message ||
        'Import failed'
      showToast(String(message), 'error')
    },
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => setMode('write')}
            className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              mode === 'write' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Code className="h-3.5 w-3.5" />
            Write
          </button>
          <button
            type="button"
            onClick={() => setMode('preview')}
            className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              mode === 'preview' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Eye className="h-3.5 w-3.5" />
            Preview
          </button>
        </div>
        {showImportFromProvider ? (
          <button
            type="button"
            disabled={fetchPromptMutation.isPending || !integrationId || !agentId?.trim()}
            onClick={() => fetchPromptMutation.mutate()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
          >
            {fetchPromptMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Import from provider
          </button>
        ) : null}
      </div>
      {mode === 'write' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full min-h-[280px] px-3 py-2.5 border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 font-mono text-sm resize-y shadow-sm"
          placeholder="Production system prompt used in evals…"
        />
      ) : (
        <div className="min-h-[280px] max-h-[60vh] overflow-y-auto border border-gray-200 rounded-lg p-4 bg-gray-50/50">
          {value.trim() ? (
            <div className={PROSE}>
              <ReactMarkdown>{value}</ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-gray-400 italic">Nothing to preview yet.</p>
          )}
        </div>
      )}
    </div>
  )
}
