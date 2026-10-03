import {
  AlertCircle,
  ArrowLeftRight,
  AudioLines,
  Check,
  Copy,
  FileText,
  MessageSquare,
  Mic,
  RefreshCw,
  Volume2,
  X,
} from 'lucide-react'

import type { CallImportRow } from '../../../types/api'
import { formatDiarisationError } from '../../../lib/diarisationErrors'
import TranscriptView from './TranscriptView'

function formatBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) return '\u2014'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

function formatRecordingDate(value: string | null | undefined): string {
  if (!value) return '-'
  const [year, month, day] = value.split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

export type CallImportRowSidePanelTabId = 'production' | 'diarised' | 'metadata'

export interface CallImportRowSidePanelContentProps {
  row: CallImportRow
  activeTab: CallImportRowSidePanelTabId
  rawColumnEntries: Array<[string, unknown]>
  hasRecording: boolean
  copiedTranscriptField: { rowId: string; field: 'production' | 'diarised' } | null
  onCopyTranscript: (
    row: CallImportRow,
    field: 'production' | 'diarised',
    event: React.MouseEvent,
  ) => void
  onDiarise: () => void
  onSwapSpeakers: () => void
  swappingRowId: string | null
  swapError: string | null
  onDismissSwapError: () => void
}

export function CallImportRowSidePanelContent({
  row,
  activeTab,
  rawColumnEntries,
  hasRecording,
  copiedTranscriptField,
  onCopyTranscript,
  onDiarise,
  onSwapSpeakers,
  swappingRowId,
  swapError,
  onDismissSwapError,
}: CallImportRowSidePanelContentProps) {
  if (activeTab === 'production') {
    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
        <header className="px-3 py-2 border-b border-gray-100 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <MessageSquare className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
            <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              Production Transcript
            </h4>
            {row.transcript ? (
              <span className="ml-1 inline-flex items-center rounded-full bg-gray-100 text-gray-700 px-2 py-0.5 text-[10px] font-medium">
                From CSV
              </span>
            ) : (
              <span className="ml-1 inline-flex items-center rounded-full bg-gray-50 text-gray-500 px-2 py-0.5 text-[10px] font-medium">
                Not provided
              </span>
            )}
          </div>
          {row.transcript ? (
            <button
              type="button"
              onClick={(e) => onCopyTranscript(row, 'production', e)}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-600 hover:text-gray-900"
              title="Copy production transcript"
            >
              {copiedTranscriptField?.rowId === row.id &&
              copiedTranscriptField?.field === 'production' ? (
                <>
                  <Check className="h-3 w-3 text-green-600" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  Copy
                </>
              )}
            </button>
          ) : null}
        </header>
        <div className="p-3 max-h-[min(38rem,calc(100vh-12rem))] overflow-y-auto">
          {row.transcript ? (
            <TranscriptView transcript={row.transcript} compact embedded />
          ) : (
            <p className="text-xs text-gray-500 italic">
              No production transcript was uploaded for this row. Map a CSV column to &quot;Transcript&quot;
              next time, or run diarisation on the Diarised tab.
            </p>
          )}
        </div>
      </div>
    )
  }

  if (activeTab === 'diarised') {
    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
        <header className="px-3 py-2 border-b border-gray-100 flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
            <AudioLines className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
            <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              Diarised Transcript
            </h4>
            {row.diarised_transcript && (
              <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 text-purple-700 px-2 py-0.5 text-[10px] font-medium">
                Diarised
                {row.diarised_transcript_provider && (
                  <span className="font-mono">
                    · {row.diarised_transcript_provider}
                    {row.diarised_transcript_model ? `/${row.diarised_transcript_model}` : ''}
                  </span>
                )}
              </span>
            )}
            {(row.diarised_transcript_status === 'pending' ||
              row.diarised_transcript_status === 'running') && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 text-blue-700 px-2 py-0.5 text-[10px] font-medium">
                <RefreshCw className="h-3 w-3 animate-spin" />
                Diarising…
              </span>
            )}
            {row.diarised_transcript_status === 'failed' && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-red-50 text-red-700 px-2 py-0.5 text-[10px] font-medium"
                title={formatDiarisationError(row.diarised_transcript_error)}
              >
                <AlertCircle className="h-3 w-3" />
                Diarisation failed
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            {row.diarised_transcript ? (
              <button
                type="button"
                onClick={(e) => onCopyTranscript(row, 'diarised', e)}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-purple-700 hover:text-purple-900"
                title="Copy diarised transcript"
              >
                {copiedTranscriptField?.rowId === row.id &&
                copiedTranscriptField?.field === 'diarised' ? (
                  <>
                    <Check className="h-3 w-3 text-green-600" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" />
                    Copy
                  </>
                )}
              </button>
            ) : null}
            {Array.isArray(row.diarised_segments) && row.diarised_segments.length > 0 ? (
              <button
                type="button"
                onClick={onSwapSpeakers}
                disabled={
                  swappingRowId === row.id ||
                  row.diarised_transcript_status === 'pending' ||
                  row.diarised_transcript_status === 'running'
                }
                title={
                  row.diarised_speaker_swap
                    ? 'Speaker labels have been swapped. Click to revert.'
                    : 'Swap user and agent labels on this row.'
                }
                className="inline-flex items-center gap-1 text-[11px] font-medium text-purple-700 hover:text-purple-900 disabled:opacity-50"
              >
                {swappingRowId === row.id ? (
                  <RefreshCw className="h-3 w-3 animate-spin" />
                ) : (
                  <ArrowLeftRight className="h-3 w-3" />
                )}
                Swap user/agent
                {row.diarised_speaker_swap ? (
                  <span className="text-[9px] uppercase tracking-wider text-purple-500">(swapped)</span>
                ) : null}
              </button>
            ) : null}
            {hasRecording ? (
              <button
                type="button"
                onClick={onDiarise}
                disabled={
                  row.diarised_transcript_status === 'pending' ||
                  row.diarised_transcript_status === 'running'
                }
                className="inline-flex items-center gap-1 text-[11px] font-medium text-purple-700 hover:text-purple-900 disabled:opacity-50"
              >
                <Mic className="h-3 w-3" />
                {row.diarised_transcript ? 'Re-diarise' : 'Diarise'}
              </button>
            ) : null}
          </div>
        </header>
        {swapError && swappingRowId === null ? (
          <div className="border-b border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
            <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1 break-words">{swapError}</div>
            <button
              type="button"
              onClick={onDismissSwapError}
              className="text-red-600 hover:text-red-800 flex-shrink-0"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}
        {row.diarised_transcript_status === 'failed' && row.diarised_transcript_error ? (
          <div className="border-b border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
            <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1 break-words">
              <span className="font-medium">Diarisation failed:</span>{' '}
              {formatDiarisationError(row.diarised_transcript_error)}
            </div>
          </div>
        ) : null}
        <div className="p-3 max-h-[min(38rem,calc(100vh-12rem))] overflow-y-auto">
          {row.diarised_transcript ? (
            <TranscriptView transcript={row.diarised_transcript} compact embedded />
          ) : (
            <p className="text-xs text-gray-500 italic">
              {hasRecording
                ? 'No diarised transcript yet. Click Diarise to run STT on this recording.'
                : 'No recording available for this row, so diarisation cannot run.'}
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <section className="bg-white border border-gray-200 rounded-lg shadow-sm">
        <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
          <Volume2 className="h-3.5 w-3.5 text-gray-400" />
          <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Recording</h4>
        </header>
        <dl className="p-3 space-y-1.5 text-xs">
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Size</dt>
            <dd className="text-gray-800 tabular-nums">{formatBytes(row.recording_size_bytes)}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Type</dt>
            <dd className="text-gray-800 truncate text-right">{row.recording_content_type || '—'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Recording date</dt>
            <dd className="text-gray-800 text-right">{formatRecordingDate(row.recording_date)}</dd>
          </div>
          {row.recording_url ? (
            <div className="flex flex-col gap-0.5 pt-1 border-t border-gray-50">
              <dt className="text-gray-500">Source URL</dt>
              <dd className="min-w-0">
                <a
                  href={row.recording_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-700 hover:text-blue-800 underline break-all"
                  title={row.recording_url}
                >
                  {row.recording_url}
                </a>
              </dd>
            </div>
          ) : null}
        </dl>
      </section>

      <section className="bg-white border border-gray-200 rounded-lg shadow-sm">
        <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
          <RefreshCw className="h-3.5 w-3.5 text-gray-400" />
          <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Run</h4>
        </header>
        <dl className="p-3 space-y-1.5 text-xs">
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Attempts</dt>
            <dd className="text-gray-800 tabular-nums">{row.attempts}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Created</dt>
            <dd className="text-gray-800 text-right">{new Date(row.created_at).toLocaleString()}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Updated</dt>
            <dd className="text-gray-800 text-right">{new Date(row.updated_at).toLocaleString()}</dd>
          </div>
        </dl>
      </section>

      {rawColumnEntries.length > 0 ? (
        <section className="bg-white border border-gray-200 rounded-lg shadow-sm">
          <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5 text-gray-400" />
            <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              Imported columns
            </h4>
            <span className="ml-1 inline-flex items-center justify-center rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
              {rawColumnEntries.length}
            </span>
          </header>
          <dl className="p-3 grid grid-cols-1 gap-2 text-xs">
            {rawColumnEntries.map(([key, value]) => {
              const stringValue = value === null || value === undefined ? '' : String(value)
              return (
                <div key={key} className="bg-gray-50 border border-gray-200 rounded px-2.5 py-1.5">
                  <dt className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider truncate">
                    {key}
                  </dt>
                  <dd className="text-gray-800 break-words mt-0.5 whitespace-pre-wrap">
                    {stringValue.trim() ? (
                      stringValue
                    ) : (
                      <span className="italic text-gray-400">empty</span>
                    )}
                  </dd>
                </div>
              )
            })}
          </dl>
        </section>
      ) : null}
    </div>
  )
}
