import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Loader2, Paperclip, Plus, Send, Sparkles, Square, Trash2, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import type { CopilotAction, CopilotSession, CopilotStatus } from '../../lib/copilotApi'
import { CopilotMessageView } from './CopilotMessages'
import { pageContextFromPath } from './pageContext'
import { useCopilotChat } from './useCopilotChat'
import { useCopilotStore } from '../../store/copilotStore'

const MAX_CHARS = 8000
const SESSION_KEY = 'copilot:lastSession'
const SUGGESTIONS = [
  'How many evals ran this week?',
  'Help me set up a test agent for one of my agents',
  'What failed yesterday?',
  'Which metrics can I use?',
]
const PROVIDERS: { value: string; label: string }[] = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'google', label: 'Google (Gemini)' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'mistral', label: 'Mistral' },
]

function readStoredSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function storeSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id)
    else localStorage.removeItem(SESSION_KEY)
  } catch {
    // Storage blocked: the panel just starts a new chat next time.
  }
}

/** Shown until the org has an LLM the assistant can use. Keys go straight to /aiproviders, never into chat. */
function SetupCard({ status, onReady }: { status: CopilotStatus; onReady: () => void }) {
  const [provider, setProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const noLlm = status.reasons.some((r) => r.code === 'no_llm')

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await apiClient.createAIProvider({ provider, api_key: apiKey.trim(), name: 'Assistant' })
      setApiKey('')
      onReady()
    } catch (err) {
      setError(getApiErrorMessage(err, 'Could not save the provider.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="m-4 rounded-xl border border-gray-200 bg-white p-4 text-sm">
      <div className="mb-1 font-medium text-gray-900">Connect an LLM to use the assistant</div>
      {status.reasons.map((r) => (
        <p key={r.code} className="mb-3 text-gray-600">
          {r.message}
        </p>
      ))}
      {noLlm && (
        <div className="space-y-2">
          <select
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          <input
            type="password"
            autoComplete="off"
            placeholder="API key"
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          {error && <p className="text-xs text-red-600">{error}</p>}
          <button
            type="button"
            disabled={!apiKey.trim() || saving}
            onClick={save}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-gray-900 px-3 py-1.5 text-white disabled:opacity-50"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Save and continue
          </button>
          <p className="text-xs text-gray-500">
            Stored encrypted in Settings → AI Providers, where you can add more providers or pick models.
          </p>
        </div>
      )}
      {!noLlm && (
        <button type="button" onClick={onReady} className="text-sm font-medium text-gray-900 underline">
          Check again
        </button>
      )}
    </div>
  )
}

function SessionList({
  activeId,
  onSelect,
}: {
  activeId: string | null
  onSelect: (id: string | null) => void
}) {
  const queryClient = useQueryClient()
  const [extra, setExtra] = useState<CopilotSession[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['copilot', 'sessions'],
    queryFn: () => apiClient.copilot.listSessions(),
  })
  useEffect(() => {
    setExtra([])
    setCursor(data?.next_cursor ?? null)
  }, [data])
  const sessions = [...(data?.items ?? []), ...extra]

  return (
    <div className="flex-1 overflow-y-auto p-2">
      {isLoading && <Loader2 className="m-4 h-4 w-4 animate-spin text-gray-400" />}
      {!isLoading && sessions.length === 0 && <p className="p-4 text-sm text-gray-500">No conversations yet.</p>}
      {sessions.map((s) => (
        <div
          key={s.id}
          className={`group flex items-center rounded-md px-2 py-1.5 text-sm ${
            s.id === activeId ? 'bg-gray-100' : 'hover:bg-gray-50'
          }`}
        >
          <button type="button" className="min-w-0 flex-1 truncate text-left text-gray-800" onClick={() => onSelect(s.id)}>
            {s.title || 'New conversation'}
          </button>
          <button
            type="button"
            aria-label="Delete conversation"
            className="ml-1 hidden text-gray-400 hover:text-red-600 group-hover:block"
            onClick={async () => {
              await apiClient.copilot.deleteSession(s.id)
              if (s.id === activeId) onSelect(null)
              queryClient.invalidateQueries({ queryKey: ['copilot', 'sessions'] })
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {cursor && (
        <button
          type="button"
          className="w-full py-2 text-xs text-gray-500 hover:text-gray-800"
          onClick={async () => {
            const page = await apiClient.copilot.listSessions(cursor)
            setExtra((current) => [...current, ...page.items])
            setCursor(page.next_cursor)
          }}
        >
          Load more
        </button>
      )}
    </div>
  )
}

export function CopilotPanel({ onClose }: { onClose: () => void }) {
  const location = useLocation()
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState<string | null>(readStoredSession)
  const [showHistory, setShowHistory] = useState(false)
  const [draft, setDraft] = useState('')
  const pending = useRef<{ sessionId: string; text: string } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pageContext = useMemo(() => pageContextFromPath(location.pathname), [location.pathname])

  const statusQuery = useQuery({
    queryKey: ['copilot', 'status'],
    queryFn: () => apiClient.copilot.status(),
    staleTime: 60_000,
  })
  const chat = useCopilotChat(sessionId)
  const actionsQuery = useQuery({
    queryKey: ['copilot', 'actions', sessionId],
    queryFn: () => apiClient.copilot.listActions(sessionId as string),
    enabled: Boolean(sessionId),
  })
  const actions = useMemo(
    () => Object.fromEntries((actionsQuery.data?.items ?? []).map((a) => [a.id, a])) as Record<string, CopilotAction>,
    [actionsQuery.data],
  )
  const onActionChanged = (action: CopilotAction) => {
    queryClient.setQueryData<{ items: CopilotAction[] }>(['copilot', 'actions', sessionId], (current) => ({
      items: [action, ...(current?.items ?? []).filter((a) => a.id !== action.id)],
    }))
    // Confirm/undo add an event line to the conversation, and may create things other pages show.
    void chat.refresh()
    void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'copilot' })
  }

  const selectSession = (id: string | null) => {
    setSessionId(id)
    storeSession(id)
    setShowHistory(false)
  }

  // A remembered session that no longer exists (deleted, other workspace): start fresh.
  useEffect(() => {
    if (chat.error === 'Could not load this conversation.') {
      selectSession(null)
      chat.setError(null)
    }
  }, [chat.error]) // eslint-disable-line react-hooks/exhaustive-deps

  // Send a message queued while its new session was being created and loaded.
  useEffect(() => {
    const queued = pending.current
    if (queued && queued.sessionId === sessionId && !chat.loading) {
      pending.current = null
      void chat.send(queued.text, pageContext, queued.sessionId).then(() =>
        queryClient.invalidateQueries({ queryKey: ['copilot', 'sessions'] }),
      )
    }
  }, [sessionId, chat.loading]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [chat.messages])

  // A page asked to open the assistant with a first message ("Set up with AI").
  const pendingPrompt = useCopilotStore((state) => state.pendingPrompt)
  useEffect(() => {
    if (!pendingPrompt || !statusQuery.data?.ready || chat.sending) return
    const prompt = useCopilotStore.getState().takePendingPrompt()
    // A fresh conversation keeps the request focused.
    if (prompt) void submitRef.current(prompt, { newConversation: true })
  }, [pendingPrompt, statusQuery.data?.ready]) // eslint-disable-line react-hooks/exhaustive-deps

  // A finished reply may have proposed actions: pick up their server state.
  useEffect(() => {
    if (!chat.sending && sessionId) {
      void queryClient.invalidateQueries({ queryKey: ['copilot', 'actions', sessionId] })
    }
  }, [chat.sending]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (text: string, options: { newConversation?: boolean } = {}) => {
    const content = text.trim()
    if (!content || chat.sending || content.length > MAX_CHARS) return
    setDraft('')
    if (sessionId && !options.newConversation) {
      await chat.send(content, pageContext)
      queryClient.invalidateQueries({ queryKey: ['copilot', 'sessions'] })
      return
    }
    try {
      const created = await apiClient.copilot.createSession()
      pending.current = { sessionId: created.id, text: content }
      selectSession(created.id)
    } catch {
      chat.setError('Could not start a conversation. Try again.')
      setDraft(content)
    }
  }

  // Upload a CSV/XLSX through the normal staged import flow, then ask the
  // assistant to map and evaluate it. The file never passes through the LLM.
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const uploadFile = async (file: File) => {
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      chat.setError('Upload a .csv or .xlsx file of calls.')
      return
    }
    setUploading(true)
    chat.setError(null)
    try {
      const created = await apiClient.callImports.createCallImport(file, { dataset: file.name.replace(/\.[^.]+$/, '') })
      await submit(
        `I uploaded "${file.name}" as a new import (id ${created.id}). Help me map its columns and then evaluate the calls.`,
      )
    } catch (err) {
      chat.setError(getApiErrorMessage(err, 'Upload failed.'))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const submitRef = useRef(submit)
  submitRef.current = submit

  const status = statusQuery.data
  const streaming = chat.sending

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-gray-200 bg-white shadow-xl sm:w-[420px]"
      aria-label="EAI assistant"
    >
      <header className="flex items-center gap-2 border-b border-gray-200 px-3 py-2.5">
        <Sparkles className="h-4 w-4 text-gray-700" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-gray-900">Assistant</div>
          {status?.ready && status.model && (
            <div className="truncate text-[11px] text-gray-500">Using {status.model}</div>
          )}
        </div>
        <button type="button" title="Conversations" className="rounded p-1 text-gray-500 hover:bg-gray-100" onClick={() => setShowHistory((v) => !v)}>
          <History className="h-4 w-4" />
        </button>
        <button type="button" title="New conversation" className="rounded p-1 text-gray-500 hover:bg-gray-100" onClick={() => selectSession(null)}>
          <Plus className="h-4 w-4" />
        </button>
        <button type="button" title="Close" className="rounded p-1 text-gray-500 hover:bg-gray-100" onClick={onClose}>
          <X className="h-4 w-4" />
        </button>
      </header>

      {statusQuery.isLoading && <Loader2 className="m-6 h-5 w-5 animate-spin text-gray-400" />}
      {statusQuery.isError && <p className="m-4 text-sm text-red-600">Could not reach the assistant.</p>}
      {status && !status.ready && <SetupCard status={status} onReady={() => statusQuery.refetch()} />}

      {status?.ready && showHistory && <SessionList activeId={sessionId} onSelect={selectSession} />}

      {status?.ready && !showHistory && (
        <>
          {status.warnings.map((w) => (
            <div key={w.code} className="border-b border-amber-100 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
              {w.message}
            </div>
          ))}
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {chat.hasMore && (
              <button type="button" className="w-full text-xs text-gray-500 hover:text-gray-800" onClick={chat.loadOlder}>
                Load earlier messages
              </button>
            )}
            {chat.loading && <Loader2 className="h-4 w-4 animate-spin text-gray-400" />}
            {!chat.loading && chat.messages.length === 0 && (
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  Ask about your agents, evaluations and imports, or have me draft a test setup.
                </p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="block w-full rounded-lg border border-gray-200 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    onClick={() => submit(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            {chat.messages.map((m) => (
              <CopilotMessageView key={m.id} message={m} actions={actions} onActionChanged={onActionChanged} />
            ))}
          </div>

          {chat.error && <div className="mx-3 mb-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{chat.error}</div>}

          <form
            className="border-t border-gray-200 p-3"
            onSubmit={(e) => {
              e.preventDefault()
              void submit(draft)
            }}
          >
            <div className="flex items-end gap-2 rounded-xl border border-gray-300 px-3 py-2 focus-within:border-gray-500">
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) void uploadFile(file)
                }}
              />
              <button
                type="button"
                title="Upload calls (CSV or Excel)"
                disabled={uploading || streaming}
                className="rounded p-1 text-gray-400 hover:text-gray-700 disabled:opacity-40"
                onClick={() => fileRef.current?.click()}
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
              </button>
              <textarea
                rows={1}
                value={draft}
                maxLength={MAX_CHARS}
                placeholder="Ask the assistant…"
                className="max-h-40 min-h-[24px] flex-1 resize-none border-0 p-0 text-sm focus:outline-none focus:ring-0"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    void submit(draft)
                  }
                }}
              />
              {streaming ? (
                <button type="button" title="Stop" onClick={chat.stop} className="rounded-md bg-gray-900 p-1.5 text-white">
                  <Square className="h-3.5 w-3.5" />
                </button>
              ) : (
                <button type="submit" title="Send" disabled={!draft.trim()} className="rounded-md bg-gray-900 p-1.5 text-white disabled:opacity-40">
                  <Send className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <p className="mt-1.5 text-[11px] text-gray-400">
              Answers cover your current workspace. Drafts aren't saved until you save them.
            </p>
          </form>
        </>
      )}
    </aside>
  )
}

export function CopilotLauncher() {
  const open = useCopilotStore((state) => state.open)
  const setOpen = useCopilotStore((state) => state.setOpen)
  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-30 inline-flex items-center gap-2 rounded-full bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg hover:bg-gray-800"
        >
          <Sparkles className="h-4 w-4" />
          Ask EAI
        </button>
      )}
      {open && <CopilotPanel onClose={() => setOpen(false)} />}
    </>
  )
}
