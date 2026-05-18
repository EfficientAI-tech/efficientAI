import { MessageSquare } from 'lucide-react'

/**
 * Renders a CSV-imported transcript as either a chat-style conversation
 * (when speakers are detectable) or formatted plain text.
 *
 * We support three input shapes that imports tend to land in:
 *
 *   1. **JSON** — an array of message objects (Retell / Vapi / OpenAI shape):
 *      ``[{"role": "user", "content": "Hi"}, {"role": "agent", "content": "Hello"}]``
 *      Either a top-level array or ``{ messages: [...] }`` is fine.
 *
 *   2. **Line-prefixed text** — one turn per line with a ``Speaker:`` prefix,
 *      optionally preceded by a ``[HH:MM]`` timestamp:
 *      ``User: hi``, ``Agent: hello``, ``[00:01:05] Caller: thanks``.
 *      Continuation lines (no speaker prefix) are appended to the prior turn.
 *
 *   3. **Plain text** — anything else falls through to a styled
 *      whitespace-preserving block so the operator can still read it.
 *
 * We only switch into chat-bubble mode when we can identify ≥ 2 distinct
 * speakers across ≥ 2 turns; otherwise we fall back to the plain-text
 * renderer to avoid producing a misleading single-speaker conversation.
 */

export interface TranscriptTurn {
  speaker: string
  side: 'user' | 'agent' | 'other'
  content: string
  timestamp?: string
}

const USER_LABEL_RE =
  /\b(user|caller|customer|human|visitor|client|patient|guest|consumer|caller_a|party_a)\b/i
const AGENT_LABEL_RE =
  /\b(agent|bot|assistant|ai|operator|support|representative|advisor|exec|executive|rep|caller_b|party_b|host|system)\b/i

export function classifySpeaker(speaker: string): TranscriptTurn['side'] {
  const s = speaker.trim()
  if (!s) return 'other'
  if (USER_LABEL_RE.test(s)) return 'user'
  if (AGENT_LABEL_RE.test(s)) return 'agent'
  return 'other'
}

function tryParseJsonTurns(text: string): TranscriptTurn[] | null {
  const trimmed = text.trim()
  if (!(trimmed.startsWith('[') || trimmed.startsWith('{'))) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return null
  }
  let arr: unknown[] | null = null
  if (Array.isArray(parsed)) {
    arr = parsed
  } else if (
    parsed &&
    typeof parsed === 'object' &&
    Array.isArray((parsed as { messages?: unknown }).messages)
  ) {
    arr = (parsed as { messages: unknown[] }).messages
  } else if (
    parsed &&
    typeof parsed === 'object' &&
    Array.isArray((parsed as { transcript?: unknown }).transcript)
  ) {
    arr = (parsed as { transcript: unknown[] }).transcript
  }
  if (!arr || arr.length === 0) return null
  const turns: TranscriptTurn[] = []
  for (const item of arr) {
    if (!item || typeof item !== 'object') return null
    const obj = item as Record<string, unknown>
    const speakerRaw =
      pickString(obj.role) ??
      pickString(obj.speaker) ??
      pickString(obj.from) ??
      pickString(obj.author) ??
      pickString(obj.who) ??
      ''
    const content =
      pickString(obj.content) ??
      pickString(obj.text) ??
      pickString(obj.message) ??
      pickString(obj.transcript) ??
      pickString(obj.value)
    if (!speakerRaw || content === undefined) return null
    const timestamp =
      pickString(obj.timestamp) ??
      pickString(obj.start_time) ??
      pickString(obj.time)
    turns.push({
      speaker: speakerRaw,
      side: classifySpeaker(speakerRaw),
      content,
      timestamp: timestamp || undefined,
    })
  }
  return turns.length > 0 ? turns : null
}

function pickString(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return undefined
}

function tryParseLineTurns(text: string): TranscriptTurn[] | null {
  const lines = text.split(/\r?\n/)
  // Optional [HH:MM] / [HH:MM:SS] timestamp, then a Speaker label (max ~30
  // chars, letters/digits/space/_/-), then any of `:`, `>`, `-` and content.
  const speakerRe =
    /^\s*(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+)?([A-Za-z][A-Za-z0-9 _\-]{0,30}?)\s*[:>\-]\s*(.+)$/
  const turns: TranscriptTurn[] = []
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    const match = line.match(speakerRe)
    if (match) {
      const ts = match[1] || undefined
      const speaker = match[2].trim()
      const content = match[3].trim()
      // Skip degenerate matches like "URL: https://..." where the label is
      // really part of a key/value pair (no alphabetic content after).
      if (!speaker || !content) continue
      turns.push({
        speaker,
        side: classifySpeaker(speaker),
        content,
        timestamp: ts,
      })
    } else if (turns.length > 0) {
      turns[turns.length - 1].content += '\n' + line
    } else {
      return null
    }
  }
  if (turns.length < 2) return null
  const distinctSpeakers = new Set(turns.map((t) => t.speaker.toLowerCase()))
  if (distinctSpeakers.size < 2) return null
  return turns
}

/**
 * Normalize literal escape sequences to real newlines.
 *
 * CSV cells routinely contain transcripts that were JSON-serialized
 * elsewhere, so the field arrives as a single line with the two-character
 * sequences ``\n`` / ``\r\n`` / ``\r`` standing in for real line breaks.
 * Python's ``csv.DictReader`` does not unescape these, so we have to do it
 * client-side before line-splitting can find the speaker prefixes.
 */
function unescapeLiteralLineBreaks(text: string): string {
  return text
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\n')
}

export function parseTranscript(text: string): TranscriptTurn[] | null {
  if (!text || !text.trim()) return null
  // JSON parsing must see the original string — JSON.parse already turns
  // ``\n`` escapes inside string values into real newlines, and unescaping
  // them up-front would produce invalid JSON (raw control chars in strings).
  const fromJson = tryParseJsonTurns(text)
  if (fromJson) return fromJson
  // Line-prefixed fallback only kicks in once we have actual newlines to
  // split on, so normalize literal escape sequences first.
  return tryParseLineTurns(unescapeLiteralLineBreaks(text))
}

interface TranscriptViewProps {
  transcript: string | null | undefined
  /** When true, renders a tighter version suitable for inline expansion. */
  compact?: boolean
}

export default function TranscriptView({
  transcript,
  compact = false,
}: TranscriptViewProps) {
  if (!transcript || !transcript.trim()) {
    return (
      <div className="text-sm text-gray-400 italic flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-gray-300" />
        No transcript available for this row.
      </div>
    )
  }

  const turns = parseTranscript(transcript)

  if (!turns) {
    return (
      <pre className="whitespace-pre-wrap break-words text-sm text-gray-800 leading-relaxed bg-gray-50 border border-gray-100 rounded-lg p-3 font-sans">
        {transcript}
      </pre>
    )
  }

  return (
    <div
      className={`space-y-2 ${
        compact ? 'max-h-96' : 'max-h-[480px]'
      } overflow-y-auto pr-1`}
    >
      {turns.map((turn, idx) => {
        const isUser = turn.side === 'user'
        const isAgent = turn.side === 'agent'
        // Other / unknown speakers get a neutral palette so we don't lie
        // about the side.
        const bubbleClass = isUser
          ? 'bg-indigo-600 text-white rounded-br-sm'
          : isAgent
            ? 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
            : 'bg-amber-50 border border-amber-200 text-amber-900 rounded-bl-sm'
        const labelClass = isUser
          ? 'text-indigo-200'
          : isAgent
            ? 'text-gray-400'
            : 'text-amber-700'
        return (
          <div
            key={idx}
            className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${bubbleClass}`}>
              <div
                className={`flex items-center gap-2 mb-0.5 text-[10px] font-semibold uppercase tracking-wider ${labelClass}`}
              >
                <span>{turn.speaker}</span>
                {turn.timestamp && (
                  <span className="tabular-nums font-normal opacity-80">
                    {turn.timestamp}
                  </span>
                )}
              </div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                {turn.content}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}
