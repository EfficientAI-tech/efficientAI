import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  X as XIcon,
  ChevronLeft,
  ChevronRight,
  SkipForward,
  Search,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { JudgeSample } from '../../lib/api'
import Button from '../../components/Button'

interface Props {
  datasetId: string
  labeledCount: number
  totalCount: number
  minEval: number
  minOpt: number
  inputField?: string
  outputField?: string
}

const FIELD_LABELS: Record<string, { title: string; subtitle: string }> = {
  user: {
    title: 'User turns',
    subtitle: 'What the test agent / customer said',
  },
  agent: {
    title: 'Agent turns',
    subtitle: "Voice AI's responses (what you're judging)",
  },
  input: { title: 'Input', subtitle: 'Sample input' },
  output: { title: 'Output', subtitle: 'Sample output' },
}

function paneLabels(field: string | undefined, fallback: 'input' | 'output') {
  const key = field || fallback
  return (
    FIELD_LABELS[key] || {
      title: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      subtitle: '',
    }
  )
}

export default function LabelingView({
  datasetId,
  labeledCount,
  totalCount,
  minEval,
  minOpt,
  inputField,
  outputField,
}: Props) {
  const queryClient = useQueryClient()
  const { data: samples = [], isLoading } = useQuery({
    queryKey: ['judge-samples', datasetId],
    queryFn: () => apiClient.listJudgeSamples(datasetId, { limit: 1000 }),
  })

  const [cursor, setCursor] = useState(0)

  // Snap to first unlabeled sample on initial load.
  useEffect(() => {
    if (samples.length === 0) return
    const firstUnlabeled = samples.findIndex((s: JudgeSample) => !s.label)
    if (firstUnlabeled >= 0) setCursor(firstUnlabeled)
  }, [samples.length])

  const sample = samples[cursor]

  const labelMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: 'pass' | 'fail' | null }) =>
      apiClient.labelJudgeSample(id, label),
    onSuccess: (updated) => {
      queryClient.setQueryData<JudgeSample[]>(
        ['judge-samples', datasetId],
        (old) => old?.map((s) => (s.id === updated.id ? updated : s)) ?? []
      )
      queryClient.invalidateQueries({ queryKey: ['judge-dataset', datasetId] })
    },
  })

  const goNext = () => setCursor((c) => Math.min(c + 1, samples.length - 1))
  const goPrev = () => setCursor((c) => Math.max(c - 1, 0))

  const setLabel = (label: 'pass' | 'fail' | null) => {
    if (!sample) return
    labelMutation.mutate({ id: sample.id, label })
    if (label !== null) {
      // Auto-advance after a label, AlignEval-style.
      setTimeout(goNext, 80)
    }
  }

  // Keyboard shortcuts: 1 = fail, 0 = pass, ArrowRight/Left navigate.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        return
      }
      if (e.key === '1') setLabel('fail')
      else if (e.key === '0') setLabel('pass')
      else if (e.key === 'ArrowRight' || e.key === 'j') goNext()
      else if (e.key === 'ArrowLeft' || e.key === 'k') goPrev()
      else if (e.key === 's') goNext()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sample, samples.length])

  const labeledPct = totalCount > 0 ? (labeledCount / totalCount) * 100 : 0
  const evalPct = Math.min(100, (labeledCount / Math.max(1, minEval)) * 100)
  const optPct = Math.min(100, (labeledCount / Math.max(1, minOpt)) * 100)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
      </div>
    )
  }

  if (samples.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-12 text-center">
        <p className="text-sm text-gray-500">
          This dataset has no samples yet. If you imported from voice
          transcripts, make sure the chosen agent has evaluator results with
          transcriptions attached.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <ProgressStrip
        labeledCount={labeledCount}
        totalCount={totalCount}
        labeledPct={labeledPct}
        evalPct={evalPct}
        optPct={optPct}
        minEval={minEval}
        minOpt={minOpt}
      />

      <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div className="text-sm text-gray-600">
            Sample <span className="font-mono">{cursor + 1}</span> /{' '}
            {samples.length}
            {sample?.external_id && (
              <span className="ml-3 text-xs text-gray-400 font-mono">
                {sample.external_id}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<ChevronLeft className="h-4 w-4" />}
              onClick={goPrev}
              disabled={cursor === 0}
            >
              Prev
            </Button>
            <Button
              variant="ghost"
              size="sm"
              rightIcon={<ChevronRight className="h-4 w-4" />}
              onClick={goNext}
              disabled={cursor >= samples.length - 1}
            >
              Next
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 divide-x divide-gray-200">
          <Pane
            title={paneLabels(inputField, 'input').title}
            subtitle={paneLabels(inputField, 'input').subtitle}
            body={sample?.input_text ?? ''}
          />
          <Pane
            title={paneLabels(outputField, 'output').title}
            subtitle={paneLabels(outputField, 'output').subtitle}
            body={sample?.output_text ?? ''}
          />
        </div>

        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <KeyHint keyName="1" label="Fail" />
            <KeyHint keyName="0" label="Pass" />
            <KeyHint keyName="←/→" label="Prev/Next" />
          </div>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              leftIcon={<SkipForward className="h-4 w-4" />}
              onClick={() => setLabel(null)}
              disabled={!sample}
            >
              Clear
            </Button>
            <Button
              variant="danger"
              leftIcon={<XIcon className="h-4 w-4" />}
              onClick={() => setLabel('fail')}
              disabled={!sample}
            >
              Fail (1)
            </Button>
            <Button
              variant="success"
              leftIcon={<Check className="h-4 w-4" />}
              onClick={() => setLabel('pass')}
              disabled={!sample}
            >
              Pass (0)
            </Button>
          </div>
        </div>
      </div>

      {sample?.label && (
        <div className="text-sm text-gray-600">
          Current label:{' '}
          <span
            className={`px-2 py-0.5 rounded font-medium ${
              sample.label === 'fail'
                ? 'bg-red-100 text-red-700'
                : 'bg-green-100 text-green-700'
            }`}
          >
            {sample.label}
          </span>
          {sample.labeled_by && (
            <span className="ml-2 text-xs text-gray-400">
              by {sample.labeled_by}
            </span>
          )}
        </div>
      )}

      <SamplesTable
        samples={samples}
        currentIndex={cursor}
        inputTitle={paneLabels(inputField, 'input').title}
        outputTitle={paneLabels(outputField, 'output').title}
        onJump={(i) => setCursor(i)}
        onLabel={(id, label) => labelMutation.mutate({ id, label })}
      />
    </div>
  )
}

function SamplesTable({
  samples,
  currentIndex,
  inputTitle,
  outputTitle,
  onJump,
  onLabel,
}: {
  samples: JudgeSample[]
  currentIndex: number
  inputTitle: string
  outputTitle: string
  onJump: (index: number) => void
  onLabel: (id: string, label: 'pass' | 'fail' | null) => void
}) {
  const [filter, setFilter] = useState<'all' | 'pass' | 'fail' | 'unlabeled'>(
    'all'
  )
  const [query, setQuery] = useState('')

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return samples
      .map((s, idx) => ({ s, idx }))
      .filter(({ s }) => {
        if (filter === 'pass' && s.label !== 'pass') return false
        if (filter === 'fail' && s.label !== 'fail') return false
        if (filter === 'unlabeled' && s.label) return false
        if (!q) return true
        return (
          (s.external_id || '').toLowerCase().includes(q) ||
          (s.input_text || '').toLowerCase().includes(q) ||
          (s.output_text || '').toLowerCase().includes(q)
        )
      })
  }, [samples, filter, query])

  const counts = useMemo(() => {
    let pass = 0
    let fail = 0
    let unlabeled = 0
    for (const s of samples) {
      if (s.label === 'pass') pass++
      else if (s.label === 'fail') fail++
      else unlabeled++
    }
    return { pass, fail, unlabeled, total: samples.length }
  }, [samples])

  if (samples.length === 0) return null

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
      <div className="flex flex-col gap-3 px-4 py-3 border-b border-gray-200 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900">All samples</h3>
          <span className="text-xs text-gray-500">
            ({rows.length} of {counts.total} shown)
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-gray-200 p-0.5">
            <FilterChip
              active={filter === 'all'}
              onClick={() => setFilter('all')}
              label={`All ${counts.total}`}
            />
            <FilterChip
              active={filter === 'pass'}
              onClick={() => setFilter('pass')}
              label={`Pass ${counts.pass}`}
              tone="success"
            />
            <FilterChip
              active={filter === 'fail'}
              onClick={() => setFilter('fail')}
              label={`Fail ${counts.fail}`}
              tone="danger"
            />
            <FilterChip
              active={filter === 'unlabeled'}
              onClick={() => setFilter('unlabeled')}
              label={`Unlabeled ${counts.unlabeled}`}
              tone="muted"
            />
          </div>
          <div className="relative">
            <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-gray-400 pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search id or text..."
              className="pl-7 pr-2 py-1.5 text-xs rounded-md border border-gray-300 w-56 focus:outline-none focus:ring-2 focus:ring-yellow-400"
            />
          </div>
        </div>
      </div>

      <div className="max-h-[60vh] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500 sticky top-0 z-10">
            <tr>
              <th className="text-left px-3 py-2 font-medium w-12">#</th>
              <th className="text-left px-3 py-2 font-medium w-44">Sample</th>
              <th className="text-left px-3 py-2 font-medium">{inputTitle}</th>
              <th className="text-left px-3 py-2 font-medium">{outputTitle}</th>
              <th className="text-left px-3 py-2 font-medium w-28">Label</th>
              <th className="text-right px-3 py-2 font-medium w-44">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ s, idx }) => {
              const isActive = idx === currentIndex
              return (
                <tr
                  key={s.id}
                  onClick={() => onJump(idx)}
                  className={`cursor-pointer border-t border-gray-100 hover:bg-yellow-50 ${
                    isActive ? 'bg-yellow-50/70' : ''
                  }`}
                >
                  <td className="px-3 py-2 align-top text-xs text-gray-500 font-mono">
                    {idx + 1}
                  </td>
                  <td className="px-3 py-2 align-top text-xs text-gray-700 font-mono break-all">
                    {s.external_id || s.id.slice(0, 8)}
                  </td>
                  <td className="px-3 py-2 align-top text-xs text-gray-700 max-w-xs truncate" title={s.input_text}>
                    {s.input_text || <span className="text-gray-400">(empty)</span>}
                  </td>
                  <td className="px-3 py-2 align-top text-xs text-gray-700 max-w-xs truncate" title={s.output_text}>
                    {s.output_text || <span className="text-gray-400">(empty)</span>}
                  </td>
                  <td className="px-3 py-2 align-top">
                    <LabelBadge label={s.label} />
                  </td>
                  <td
                    className="px-3 py-2 align-top text-right"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="inline-flex items-center gap-1">
                      <IconBtn
                        title="Mark Pass"
                        onClick={() => onLabel(s.id, 'pass')}
                        active={s.label === 'pass'}
                        tone="success"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </IconBtn>
                      <IconBtn
                        title="Mark Fail"
                        onClick={() => onLabel(s.id, 'fail')}
                        active={s.label === 'fail'}
                        tone="danger"
                      >
                        <XIcon className="h-3.5 w-3.5" />
                      </IconBtn>
                      <IconBtn
                        title="Clear label"
                        onClick={() => onLabel(s.id, null)}
                        active={false}
                        tone="muted"
                      >
                        <SkipForward className="h-3.5 w-3.5" />
                      </IconBtn>
                    </div>
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-8 text-center text-sm text-gray-500"
                >
                  No samples match the current filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LabelBadge({ label }: { label?: string | null }) {
  if (!label) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
        unlabeled
      </span>
    )
  }
  const cls =
    label === 'fail'
      ? 'bg-red-100 text-red-700'
      : 'bg-green-100 text-green-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {label}
    </span>
  )
}

function FilterChip({
  active,
  onClick,
  label,
  tone = 'default',
}: {
  active: boolean
  onClick: () => void
  label: string
  tone?: 'default' | 'success' | 'danger' | 'muted'
}) {
  const activeClasses: Record<string, string> = {
    default: 'bg-gray-900 text-white',
    success: 'bg-green-600 text-white',
    danger: 'bg-red-600 text-white',
    muted: 'bg-gray-500 text-white',
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
        active ? activeClasses[tone] : 'text-gray-600 hover:bg-gray-100'
      }`}
    >
      {label}
    </button>
  )
}

function IconBtn({
  children,
  onClick,
  active,
  title,
  tone,
}: {
  children: React.ReactNode
  onClick: () => void
  active: boolean
  title: string
  tone: 'success' | 'danger' | 'muted'
}) {
  const map: Record<string, { active: string; idle: string }> = {
    success: {
      active: 'bg-green-600 text-white border-green-600',
      idle: 'text-green-700 border-green-200 hover:bg-green-50',
    },
    danger: {
      active: 'bg-red-600 text-white border-red-600',
      idle: 'text-red-700 border-red-200 hover:bg-red-50',
    },
    muted: {
      active: 'bg-gray-600 text-white border-gray-600',
      idle: 'text-gray-600 border-gray-200 hover:bg-gray-100',
    },
  }
  const { active: a, idle } = map[tone]
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={`inline-flex items-center justify-center h-7 w-7 rounded border transition-colors ${
        active ? a : idle
      }`}
    >
      {children}
    </button>
  )
}

function Pane({
  title,
  subtitle,
  body,
}: {
  title: string
  subtitle?: string
  body: string
}) {
  return (
    <div className="p-4">
      <div className="mb-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          {title}
        </div>
        {subtitle && (
          <div className="text-[11px] text-gray-400 mt-0.5">{subtitle}</div>
        )}
      </div>
      <div className="text-sm text-gray-900 whitespace-pre-wrap break-words max-h-[60vh] overflow-y-auto">
        {body || <span className="text-gray-400">(empty)</span>}
      </div>
    </div>
  )
}

function ProgressStrip({
  labeledCount,
  totalCount,
  labeledPct,
  evalPct,
  optPct,
  minEval,
  minOpt,
}: {
  labeledCount: number
  totalCount: number
  labeledPct: number
  evalPct: number
  optPct: number
  minEval: number
  minOpt: number
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
      <ProgressItem
        label="Labeled"
        value={`${labeledCount} / ${totalCount}`}
        pct={labeledPct}
        color="bg-yellow-400"
      />
      <ProgressItem
        label={`Evaluate unlock (${minEval})`}
        value={`${Math.min(labeledCount, minEval)} / ${minEval}`}
        pct={evalPct}
        color="bg-blue-500"
      />
      <ProgressItem
        label={`Optimize unlock (${minOpt})`}
        value={`${Math.min(labeledCount, minOpt)} / ${minOpt}`}
        pct={optPct}
        color="bg-purple-500"
      />
    </div>
  )
}

function ProgressItem({
  label,
  value,
  pct,
  color,
}: {
  label: string
  value: string
  pct: number
  color: string
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-600">{label}</span>
        <span className="font-medium text-gray-900">{value}</span>
      </div>
      <div className="mt-1 w-full bg-gray-200 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function KeyHint({ keyName, label }: { keyName: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <kbd className="px-1.5 py-0.5 bg-white border border-gray-300 rounded text-xs font-mono">
        {keyName}
      </kbd>
      <span>{label}</span>
    </span>
  )
}
