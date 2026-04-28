import { useMemo, useState } from 'react'
import { format } from 'date-fns'
import {
  Loader2,
  Trash2,
  ArrowLeft,
  Share2,
  ExternalLink,
  Copy,
  Check,
  Users,
  Search,
  Lock,
} from 'lucide-react'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'
import { useToast } from '../../../../hooks/useToast'
import StatusBadge from './StatusBadge'
import ComparisonResultsView from './ComparisonResultsView'
import { TTSComparisonSummary } from '../types'

export default function BlindTestsTab() {
  const {
    pastComparisons,
    viewingPastId,
    setViewingPastId,
    viewedComparison,
    viewedLoading,
    playingId,
    play,
    stop,
    deleteComparison,
    isDeleting,
    setDeleteConfirm,
    viewedReportJob,
    isDownloading,
    isCreatingReport,
    downloadReport,
    createReportJob,
    openAsyncReport,
  } = useVoicePlayground()

  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'benchmark' | 'blind_test_only'>('all')
  const [copiedToken, setCopiedToken] = useState<string | null>(null)
  const { showToast, ToastContainer } = useToast()

  const blindTests = useMemo(() => {
    return pastComparisons.filter((c) => c.has_share)
  }, [pastComparisons])

  const filtered = useMemo(() => {
    let rows = blindTests
    if (filter !== 'all') {
      rows = rows.filter((c) => (c.mode || 'benchmark') === filter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      rows = rows.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          (c.share_title || '').toLowerCase().includes(q) ||
          (c.provider_a || '').toLowerCase().includes(q) ||
          (c.provider_b || '').toLowerCase().includes(q),
      )
    }
    return rows
  }, [blindTests, filter, search])

  const benchmarkCount = blindTests.filter((c) => (c.mode || 'benchmark') === 'benchmark').length
  const standaloneCount = blindTests.filter((c) => c.mode === 'blind_test_only').length

  const copyShareLink = async (token: string) => {
    const url = `${window.location.origin}/blind-test/${token}`
    try {
      await navigator.clipboard.writeText(url)
      setCopiedToken(token)
      showToast('Public link copied', 'success')
      setTimeout(() => setCopiedToken((t) => (t === token ? null : t)), 1500)
    } catch {
      showToast('Failed to copy link', 'error')
    }
  }

  if (viewingPastId) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => {
            setViewingPastId(null)
            stop()
          }}
          className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Blind Tests
        </button>

        {viewedLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading blind test...
          </div>
        ) : viewedComparison ? (
          <ComparisonResultsView
            comparison={viewedComparison}
            playingId={playingId}
            onPlay={play}
            isDownloading={isDownloading}
            isCreatingReport={isCreatingReport}
            reportJob={viewedReportJob || null}
            onDownloadPdf={(options) => downloadReport(viewedComparison.id, options)}
            onGenerateAsync={(options) => createReportJob(viewedComparison.id, options)}
            onOpenAsyncReport={() => openAsyncReport(viewedReportJob)}
          />
        ) : (
          <p className="text-center text-gray-500 py-8">Blind test not found</p>
        )}
        <ToastContainer />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 rounded-xl p-5">
        <div className="flex items-start gap-3">
          <Share2 className="w-5 h-5 text-amber-700 mt-0.5" />
          <div>
            <h3 className="font-semibold text-amber-900">Blind Tests</h3>
            <p className="text-sm text-amber-800 mt-1">
              All blind tests, whether they came from TTS benchmarks, recordings, or uploaded audio
              comparisons. Click a row to view aggregated rater feedback or copy the public share
              link.
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-lg p-1">
          <FilterChip
            active={filter === 'all'}
            onClick={() => setFilter('all')}
            label={`All (${blindTests.length})`}
          />
          <FilterChip
            active={filter === 'benchmark'}
            onClick={() => setFilter('benchmark')}
            label={`From Simulations (${benchmarkCount})`}
          />
          <FilterChip
            active={filter === 'blind_test_only'}
            onClick={() => setFilter('blind_test_only')}
            label={`Standalone (${standaloneCount})`}
          />
        </div>
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, provider, or share title..."
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden">
        {filtered.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            <Share2 className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            {blindTests.length === 0 ? (
              <p>
                No blind tests yet. Create one from the Playground tab — either share results from a
                TTS benchmark or use the &quot;Create Blind Test&quot; mode for standalone audio
                comparisons.
              </p>
            ) : (
              <p>No blind tests match your filters.</p>
            )}
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {filtered.map((bt) => (
              <BlindTestRow
                key={bt.id}
                bt={bt}
                onView={() => setViewingPastId(bt.id)}
                onCopyLink={() => bt.share_token && copyShareLink(bt.share_token)}
                copied={copiedToken === bt.share_token}
                onDelete={() =>
                  setDeleteConfirm({
                    message: `Delete blind test "${bt.share_title || bt.name}"? This will also delete its comparison.`,
                    onConfirm: () => deleteComparison(bt.id),
                  })
                }
                isDeleting={isDeleting}
              />
            ))}
          </div>
        )}
      </div>
      <ToastContainer />
    </div>
  )
}

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-medium rounded-md transition ${
        active ? 'bg-primary-100 text-primary-700' : 'text-gray-600 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  )
}

function BlindTestRow({
  bt,
  onView,
  onCopyLink,
  copied,
  onDelete,
  isDeleting,
}: {
  bt: TTSComparisonSummary
  onView: () => void
  onCopyLink: () => void
  copied: boolean
  onDelete: () => void
  isDeleting: boolean
}) {
  const isBenchmark = (bt.mode || 'benchmark') === 'benchmark'
  const modeBadgeClass = isBenchmark
    ? 'bg-blue-50 text-blue-700 border-blue-200'
    : 'bg-purple-50 text-purple-700 border-purple-200'
  const shareStatusClass =
    bt.share_status === 'open'
      ? 'bg-green-50 text-green-700 border-green-200'
      : 'bg-gray-100 text-gray-600 border-gray-200'

  return (
    <div className="px-6 py-4 flex items-center gap-4 hover:bg-gray-50 transition-colors">
      <div className="flex-1 min-w-0 cursor-pointer" onClick={onView}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-gray-900 truncate">
            {bt.share_title || bt.name}
          </span>
          <span
            className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${modeBadgeClass}`}
          >
            {isBenchmark ? 'From Simulation' : 'Standalone'}
          </span>
          <span
            className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${shareStatusClass}`}
          >
            {bt.share_status === 'open' ? 'Open' : 'Closed'}
          </span>
          {bt.simulation_id && (
            <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded font-mono">
              #{bt.simulation_id}
            </span>
          )}
          <StatusBadge status={bt.status} />
        </div>
        <div className="flex items-center gap-3 mt-1 text-sm text-gray-500 flex-wrap">
          {bt.provider_a && (
            <span className="flex items-center gap-1.5">
              <ProviderLogo provider={bt.provider_a} size="sm" />
              {getProviderInfo(bt.provider_a).label}
            </span>
          )}
          {bt.provider_b && (
            <>
              <span className="text-gray-300">vs</span>
              <span className="flex items-center gap-1.5">
                <ProviderLogo provider={bt.provider_b} size="sm" />
                {getProviderInfo(bt.provider_b).label}
              </span>
            </>
          )}
          {(bt.provider_a || bt.provider_b) && <span className="text-gray-300">•</span>}
          <span className="flex items-center gap-1.5">
            <Users className="w-3.5 h-3.5" />
            {bt.response_count || 0} response{(bt.response_count || 0) === 1 ? '' : 's'}
          </span>
          <span className="text-gray-300">•</span>
          <span>
            {bt.sample_count} {isBenchmark ? 'samples' : 'pairs'}
            {bt.num_runs > 1 && ` × ${bt.num_runs} runs`}
          </span>
          <span className="text-gray-300">•</span>
          <span>{format(new Date(bt.created_at), 'MMM d, yyyy HH:mm')}</span>
        </div>
        {bt.share_creator_notes && (
          <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded-md px-2 py-1.5">
            <Lock className="w-3 h-3 text-amber-600 mt-0.5 flex-shrink-0" />
            <span className="whitespace-pre-line line-clamp-2 break-words">
              {bt.share_creator_notes}
            </span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-1">
        {bt.share_token && (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="text-gray-500 hover:text-gray-700"
              onClick={onCopyLink}
              title="Copy public link"
            >
              {copied ? <Check className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
            </Button>
            <a
              href={`/blind-test/${bt.share_token}`}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors"
              title="Open public form"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          </>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="text-red-500 hover:text-red-700 hover:bg-red-50"
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
          disabled={isDeleting}
        >
          <Trash2 className="w-4 h-4" />
        </Button>
      </div>
    </div>
  )
}
