import { useMemo, useState } from 'react'
import { ExternalLink, Search } from 'lucide-react'
import {
  CallTimelineEvent,
  timelineCategoryLabel,
  TimelineCategory,
} from './callTimelineUtils'

const CATEGORY_STYLES: Record<TimelineCategory, string> = {
  call: 'bg-gray-100 text-gray-800 border-gray-200',
  stt: 'bg-purple-50 text-purple-800 border-purple-200',
  llm: 'bg-primary-50 text-primary-900 border-primary-200',
  tts: 'bg-sky-50 text-sky-800 border-sky-200',
  transport: 'bg-orange-50 text-orange-800 border-orange-200',
  message: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  analysis: 'bg-violet-50 text-violet-800 border-violet-200',
  pipeline: 'bg-indigo-50 text-indigo-800 border-indigo-200',
  s2s: 'bg-teal-50 text-teal-800 border-teal-200',
}

function formatOffset(ms: number): string {
  const totalSec = ms / 1000
  const mins = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return `${String(mins).padStart(2, '0')}:${sec.toFixed(2).padStart(5, '0')}`
}

function isUrl(text: string): boolean {
  return /^https?:\/\//i.test(text.trim())
}

export default function CallEventTimeline({
  events,
  externalLogUrl,
  emptyMessage = 'No timeline events yet.',
}: {
  events: CallTimelineEvent[]
  externalLogUrl?: string | null
  emptyMessage?: string
}) {
  const [query, setQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<TimelineCategory | 'all'>('all')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return events.filter((ev) => {
      if (categoryFilter !== 'all' && ev.category !== categoryFilter) return false
      if (!q) return true
      return (
        ev.title.toLowerCase().includes(q) ||
        (ev.detail || '').toLowerCase().includes(q) ||
        timelineCategoryLabel(ev.category).toLowerCase().includes(q)
      )
    })
  }, [events, query, categoryFilter])

  const categories = useMemo(() => {
    const set = new Set(events.map((e) => e.category))
    return Array.from(set)
  }, [events])

  if (!events.length) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white px-4 py-10 text-center text-sm text-gray-500">
        {emptyMessage}
        {externalLogUrl ? (
          <div className="mt-3">
            <a
              href={externalLogUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-800"
            >
              Open provider log
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 bg-gray-50 px-4 py-3">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-gray-400" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search timeline"
            className="w-full rounded-md border border-gray-200 bg-white py-1.5 pl-8 pr-3 text-sm"
          />
        </div>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as TimelineCategory | 'all')}
          className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700"
        >
          <option value="all">All categories</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {timelineCategoryLabel(cat)}
            </option>
          ))}
        </select>
        {externalLogUrl ? (
          <a
            href={externalLogUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
          >
            Provider log
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : null}
        <span className="text-xs text-gray-500">{filtered.length} events</span>
      </div>

      <div className="max-h-[min(70vh,560px)] overflow-y-auto">
        <div className="grid grid-cols-[5.5rem_5.5rem_1fr] gap-3 border-b border-gray-100 bg-white px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
          <span>Offset</span>
          <span>Category</span>
          <span>Event</span>
        </div>
        {filtered.map((ev) => (
          <div
            key={ev.id}
            className="grid grid-cols-[5.5rem_5.5rem_1fr] gap-3 border-b border-gray-50 px-4 py-3 text-sm hover:bg-gray-50/80"
          >
            <span className="font-mono text-xs tabular-nums text-gray-600">
              +{formatOffset(ev.offsetMs)}
            </span>
            <span>
              <span
                className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${CATEGORY_STYLES[ev.category]}`}
              >
                {timelineCategoryLabel(ev.category)}
              </span>
            </span>
            <div className="min-w-0">
              <p className={`font-medium ${ev.level === 'error' ? 'text-rose-700' : 'text-gray-900'}`}>
                {ev.title}
              </p>
              {ev.detail ? (
                <p className="mt-0.5 break-words text-xs text-gray-600">
                  {isUrl(ev.detail) ? 'See provider log link above' : ev.detail}
                </p>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
