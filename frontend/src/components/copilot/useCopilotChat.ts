import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '../../lib/api'
import {
  CopilotApiError,
  type CopilotMessage,
  type CopilotPageContext,
  type CopilotStreamEvent,
} from '../../lib/copilotApi'
import { randomId } from '../../lib/randomId'

const POLL_MS = 2000
const MAX_POLLS = 120 // matches the server's turn timeout plus margin

function userTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    return undefined
  }
}

function applyEvent(message: CopilotMessage, event: CopilotStreamEvent): CopilotMessage {
  switch (event.event) {
    case 'turn_started':
      return { ...message, id: event.data.message_id }
    case 'token':
      return { ...message, content: message.content + event.data.text }
    case 'tool_call':
      return {
        ...message,
        tool_calls: [...message.tool_calls, { id: event.data.id, name: event.data.name, status: 'running' }],
      }
    case 'tool_result':
      return {
        ...message,
        tool_calls: message.tool_calls.map((c) =>
          c.id === event.data.id ? { ...c, status: event.data.status, latency_ms: event.data.latency_ms } : c,
        ),
      }
    case 'proposal':
    case 'wizard':
    case 'draft': {
      // Attach the card to the tool call that produced it (the latest one).
      const calls = [...message.tool_calls]
      const last = calls.length - 1
      if (last >= 0) calls[last] = { ...calls[last], ui: event.data }
      return { ...message, tool_calls: calls }
    }
    case 'error':
      return { ...message, error: event.data.message }
    case 'done':
      return { ...message, status: event.data.status }
    default:
      return message
  }
}

/**
 * Messages of one copilot session, with streaming send, stop, and recovery:
 * if the stream drops (network, reload), it polls the saved reply until the
 * server finishes it. The server keeps running the turn either way.
 */
export function useCopilotChat(sessionId: string | null) {
  const [messages, setMessages] = useState<CopilotMessage[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const pollRef = useRef<number | null>(null)
  const sessionRef = useRef(sessionId)
  sessionRef.current = sessionId

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }

  const pollUntilSettled = useCallback((sid: string, attempt = 0) => {
    stopPolling()
    pollRef.current = window.setTimeout(async () => {
      if (sessionRef.current !== sid) return
      try {
        const page = await apiClient.copilot.listMessages(sid)
        if (sessionRef.current !== sid) return
        setMessages(page.items)
        setHasMore(page.has_more)
        const streaming = page.items.some((m) => m.status === 'streaming')
        if (streaming && attempt < MAX_POLLS) pollUntilSettled(sid, attempt + 1)
        else setSending(false)
      } catch {
        if (attempt < MAX_POLLS) pollUntilSettled(sid, attempt + 1)
        else setSending(false)
      }
    }, POLL_MS)
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    stopPolling()
    setMessages([])
    setHasMore(false)
    setError(null)
    setSending(false)
    if (!sessionId) return
    let cancelled = false
    setLoading(true)
    apiClient.copilot
      .listMessages(sessionId)
      .then((page) => {
        if (cancelled) return
        setMessages(page.items)
        setHasMore(page.has_more)
        if (page.items.some((m) => m.status === 'streaming')) {
          setSending(true)
          pollUntilSettled(sessionId)
        }
      })
      .catch(() => !cancelled && setError('Could not load this conversation.'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
      stopPolling()
    }
  }, [sessionId, pollUntilSettled])

  useEffect(() => () => abortRef.current?.abort(), [])

  const loadOlder = useCallback(async () => {
    if (!sessionId || !messages.length) return
    const page = await apiClient.copilot.listMessages(sessionId, messages[0].seq)
    setMessages((current) => [...page.items, ...current])
    setHasMore(page.has_more)
  }, [sessionId, messages])

  const send = useCallback(
    async (content: string, pageContext: CopilotPageContext, targetSessionId?: string) => {
      const sid = targetSessionId ?? sessionId
      if (!sid || sending) return
      setError(null)
      setSending(true)
      const now = new Date().toISOString()
      const userTemp: CopilotMessage = {
        id: `local-user-${randomId()}`,
        seq: Number.MAX_SAFE_INTEGER - 1,
        role: 'user',
        content,
        status: 'complete',
        tool_calls: [],
        created_at: now,
      }
      const replyTemp: CopilotMessage = {
        id: `local-reply-${randomId()}`,
        seq: Number.MAX_SAFE_INTEGER,
        role: 'assistant',
        content: '',
        status: 'streaming',
        tool_calls: [],
        created_at: now,
      }
      let replyId = replyTemp.id
      setMessages((current) => [...current, userTemp, replyTemp])
      const controller = new AbortController()
      abortRef.current = controller

      const update = (event: CopilotStreamEvent) => {
        setMessages((current) =>
          current.map((m) => {
            if (m.id !== replyId) return m
            const next = applyEvent(m, event)
            if (event.event === 'turn_started') replyId = next.id
            return next
          }),
        )
      }

      let finished = false
      try {
        await apiClient.copilot.sendMessage(
          sid,
          { content, client_message_id: randomId(), page_context: pageContext, timezone: userTimezone() },
          (event) => {
            update(event)
            if (event.event === 'done') {
              finished = true
              // A replayed turn may still be running elsewhere; poll for it.
              if (event.data.status === 'streaming') pollUntilSettled(sid)
            }
          },
          controller.signal,
        )
        if (!finished) pollUntilSettled(sid) // stream ended early; the server keeps going
        else setSending(false)
      } catch (err) {
        if (controller.signal.aborted) return
        if (err instanceof CopilotApiError) {
          // Refused before the turn started (limits, not ready): nothing was saved.
          setMessages((current) => current.filter((m) => m.id !== userTemp.id && m.id !== replyId))
          setError(err.message)
          setSending(false)
        } else {
          pollUntilSettled(sid) // network drop mid-stream
        }
      }
    },
    [sessionId, sending, pollUntilSettled],
  )

  const stop = useCallback(async () => {
    const sid = sessionRef.current
    const streaming = messages.find((m) => m.role === 'assistant' && m.status === 'streaming')
    if (!sid || !streaming || streaming.id.startsWith('local-')) return
    await apiClient.copilot.cancel(sid, streaming.id).catch(() => undefined)
  }, [messages])

  /** Re-read saved messages (e.g. after confirming a card adds an event). */
  const refresh = useCallback(async () => {
    const sid = sessionRef.current
    if (!sid || sending) return
    const page = await apiClient.copilot.listMessages(sid).catch(() => null)
    if (page && sessionRef.current === sid) {
      setMessages(page.items)
      setHasMore(page.has_more)
    }
  }, [sending])

  return { messages, hasMore, loading, sending, error, setError, send, stop, loadOlder, refresh }
}
