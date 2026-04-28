import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Volume2,
  X,
  XCircle,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { CallImportRow } from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'

const ROW_PAGE_SIZE = 100

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

function formatBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) return '\u2014'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

function isNonRetryableError(message: string | null | undefined): boolean {
  if (!message) return false
  return /(401|403|404|forbidden|unauthor|not found|exceeds|too large|invalid content)/i.test(message)
}

export default function CallImportDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [rowOffset, setRowOffset] = useState(0)
  const [transcriptRow, setTranscriptRow] = useState<CallImportRow | null>(null)

  const [playingRowId, setPlayingRowId] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [loadingRowId, setLoadingRowId] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  const [showDeleteImport, setShowDeleteImport] = useState(false)
  const [pendingDeleteRow, setPendingDeleteRow] = useState<CallImportRow | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const deleteImportMutation = useMutation({
    mutationFn: (importId: string) => apiClient.deleteCallImport(importId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      navigate('/call-imports')
    },
    onError: (err: any) => {
      setDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete import.',
      )
    },
  })

  const deleteRowMutation = useMutation({
    mutationFn: ({ importId, rowId }: { importId: string; rowId: string }) =>
      apiClient.deleteCallImportRow(importId, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDeleteRow(null)
      setDeleteError(null)
    },
    onError: (err: any) => {
      setDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete row.',
      )
    },
  })

  const queryParams = useMemo(
    () => ({ row_limit: ROW_PAGE_SIZE, row_offset: rowOffset }),
    [rowOffset],
  )

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey: ['call-import', id, queryParams],
    queryFn: () => apiClient.getCallImport(id!, queryParams),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'processing' ? 5000 : false
    },
  })

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
      }
    }
  }, [])

  const totalRows = data?.total_rows ?? 0
  const rowPage = Math.floor(rowOffset / ROW_PAGE_SIZE) + 1
  const rowTotalPages = Math.max(1, Math.ceil(totalRows / ROW_PAGE_SIZE))

  const handlePlay = async (row: CallImportRow) => {
    if (!row.recording_s3_key) return

    if (playingRowId === row.id && audioUrl) {
      if (isPlaying) {
        audioRef.current?.pause()
        setIsPlaying(false)
      } else {
        audioRef.current?.play()
        setIsPlaying(true)
      }
      return
    }

    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }

    setLoadingRowId(row.id)
    try {
      const { url } = await apiClient.getS3PresignedUrl(row.recording_s3_key)
      setAudioUrl(url)
      setPlayingRowId(row.id)
      setIsPlaying(true)
      setLoadingRowId(null)
      setTimeout(() => audioRef.current?.play(), 100)
    } catch (e) {
      console.error('Failed to load recording', e)
      setLoadingRowId(null)
      alert('Failed to load recording')
    }
  }

  const handleStopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
    setIsPlaying(false)
    setPlayingRowId(null)
    setAudioUrl(null)
  }

  const handleDownload = async (row: CallImportRow) => {
    if (!row.recording_s3_key) return
    try {
      const { url } = await apiClient.getS3PresignedUrl(row.recording_s3_key)
      const link = document.createElement('a')
      link.href = url
      link.setAttribute(
        'download',
        row.recording_s3_key.split('/').pop() || `${row.external_call_id}.mp3`,
      )
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (e) {
      console.error('Failed to download recording', e)
      alert('Failed to download recording')
    }
  }

  if (!id) {
    return <div className="text-sm text-red-600">Missing import id.</div>
  }

  if (isLoading) {
    return (
      <div className="text-center py-12 text-gray-500">
        <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin" />
        <p>Loading import...</p>
      </div>
    )
  }

  if (error || !data) {
    const status = (error as any)?.response?.status
    return (
      <div className="space-y-4">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Call Imports
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-red-600 mt-0.5" />
            <p className="text-sm text-red-800">
              {status === 404
                ? 'Call import not found.'
                : (error as any)?.response?.data?.detail || 'Failed to load import.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  const rows = data.rows ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Call Imports
        </Link>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            isLoading={isFetching && !isLoading}
            leftIcon={!(isFetching && !isLoading) ? <RefreshCw className="h-4 w-4" /> : undefined}
          >
            Refresh
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDeleteError(null)
              setShowDeleteImport(true)
            }}
            leftIcon={<Trash2 className="h-4 w-4" />}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            Delete Import
          </Button>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-gray-900 truncate">
              {data.original_filename || '(unnamed import)'}
            </h1>
            <div className="mt-1 text-xs text-gray-500 font-mono">{data.id}</div>
            <div className="mt-3 flex items-center gap-3 flex-wrap">
              <StatusBadge status={data.status} />
              <span className="text-sm text-gray-600 capitalize">
                Provider: <span className="font-medium">{data.provider}</span>
              </span>
              <span className="text-sm text-gray-600">
                Created: {new Date(data.created_at).toLocaleString()}
              </span>
              <span className="text-sm text-gray-600">
                Updated: {new Date(data.updated_at).toLocaleString()}
              </span>
            </div>
          </div>
          <div className="w-72 flex-shrink-0">
            <CallImportProgressBar
              total={data.total_rows}
              completed={data.completed_rows}
              failed={data.failed_rows}
            />
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
              <div className="bg-gray-50 rounded p-2">
                <div className="text-gray-500">Total</div>
                <div className="font-semibold text-gray-900">{data.total_rows}</div>
              </div>
              <div className="bg-green-50 rounded p-2">
                <div className="text-green-700">Completed</div>
                <div className="font-semibold text-green-800">{data.completed_rows}</div>
              </div>
              <div className="bg-red-50 rounded p-2">
                <div className="text-red-700">Failed</div>
                <div className="font-semibold text-red-800">{data.failed_rows}</div>
              </div>
            </div>
          </div>
        </div>

        {data.error_message && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 mt-0.5" />
              <p className="text-sm text-red-800">{data.error_message}</p>
            </div>
          </div>
        )}
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Rows</h2>
          <p className="text-sm text-gray-500">
            Showing {rows.length === 0 ? 0 : rowOffset + 1}&ndash;
            {rowOffset + rows.length} of {totalRows}
          </p>
        </div>

        {rows.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p>No rows in this slice.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-12">
                    #
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    CallID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Attempts
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Recording
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Transcript
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-12">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {rows.map((row) => {
                  const hasRecording = !!row.recording_s3_key
                  const isThisPlaying = playingRowId === row.id && isPlaying
                  return (
                    <Fragment key={row.id}>
                      <tr className="hover:bg-gray-50 align-top">
                        <td className="px-4 py-3 text-sm text-gray-500">
                          {row.row_index + 1}
                        </td>
                        <td className="px-4 py-3 text-sm font-mono text-gray-900 break-all">
                          {row.external_call_id}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={row.status} size="sm" />
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">{row.attempts}</td>
                        <td className="px-4 py-3 text-sm">
                          {hasRecording ? (
                            <div className="flex items-center gap-2 flex-wrap">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handlePlay(row)}
                                isLoading={loadingRowId === row.id}
                                leftIcon={
                                  loadingRowId === row.id
                                    ? undefined
                                    : isThisPlaying
                                      ? <Pause className="h-4 w-4" />
                                      : <Play className="h-4 w-4" />
                                }
                                className={
                                  isThisPlaying
                                    ? 'text-green-600 hover:text-green-700 bg-green-50'
                                    : 'text-blue-600 hover:text-blue-700'
                                }
                                title={isThisPlaying ? 'Pause' : 'Play'}
                              >
                                {isThisPlaying ? 'Pause' : 'Play'}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDownload(row)}
                                leftIcon={<Download className="h-4 w-4" />}
                                className="text-primary-600 hover:text-primary-700"
                              >
                                Download
                              </Button>
                              <span className="text-xs text-gray-400">
                                {formatBytes(row.recording_size_bytes)}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs text-gray-400">
                              {row.status === 'failed' ? '\u2014' : 'Pending...'}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {row.transcript ? (
                            <button
                              onClick={() => setTranscriptRow(row)}
                              className="text-left text-gray-700 hover:text-primary-700 underline-offset-2 hover:underline line-clamp-2 max-w-md"
                              title="View transcript"
                            >
                              {row.transcript.length > 120
                                ? `${row.transcript.slice(0, 120)}...`
                                : row.transcript}
                            </button>
                          ) : (
                            <span className="text-xs text-gray-400">No transcript</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            aria-label={`Delete recording for ${row.external_call_id}`}
                            title="Delete recording"
                            onClick={() => {
                              setDeleteError(null)
                              setPendingDeleteRow(row)
                            }}
                            disabled={
                              deleteRowMutation.isPending &&
                              pendingDeleteRow?.id === row.id
                            }
                            className="text-gray-400 hover:text-red-600 transition-colors disabled:opacity-40"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                      {row.status === 'failed' && row.error_message && (
                        <tr className="bg-red-50">
                          <td />
                          <td colSpan={6} className="px-4 py-2 text-xs text-red-800">
                            <div className="flex items-start gap-2">
                              <AlertCircle className="h-3.5 w-3.5 text-red-600 mt-0.5 flex-shrink-0" />
                              <div className="flex-1">
                                <span className="font-medium">Error:</span> {row.error_message}
                                {isNonRetryableError(row.error_message) && (
                                  <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700">
                                    no retry
                                  </span>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>

            {rowTotalPages > 1 && (
              <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between mt-2 rounded-b-lg">
                <p className="text-sm text-gray-600">
                  Page {rowPage} of {rowTotalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setRowOffset((o) => Math.max(0, o - ROW_PAGE_SIZE))}
                    disabled={rowOffset <= 0}
                    leftIcon={<ChevronLeft className="h-4 w-4" />}
                  >
                    Prev
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setRowOffset((o) =>
                        o + ROW_PAGE_SIZE >= totalRows ? o : o + ROW_PAGE_SIZE,
                      )
                    }
                    disabled={rowOffset + ROW_PAGE_SIZE >= totalRows}
                    rightIcon={<ChevronRight className="h-4 w-4" />}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {playingRowId && audioUrl && (
          <div className="mt-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Volume2 className="h-5 w-5 text-blue-600" />
                <span className="text-sm font-medium text-gray-700">Now Playing:</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  {rows.find((r) => r.id === playingRowId)?.external_call_id}
                </p>
              </div>
              <button
                onClick={handleStopAudio}
                className="p-2 rounded-full bg-gray-200 text-gray-600 hover:bg-gray-300 transition-colors"
                title="Stop"
              >
                <XCircle className="h-4 w-4" />
              </button>
              <audio
                ref={audioRef}
                src={audioUrl}
                onEnded={() => setIsPlaying(false)}
                onPause={() => setIsPlaying(false)}
                onPlay={() => setIsPlaying(true)}
                controls
                className="h-8 flex-shrink-0"
              />
            </div>
          </div>
        )}
      </div>

      {transcriptRow &&
        renderModal(
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]">
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold">Transcript</h3>
                  <p className="text-xs text-gray-500 font-mono truncate">
                    {transcriptRow.external_call_id}
                  </p>
                </div>
                <button
                  onClick={() => setTranscriptRow(null)}
                  className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 overflow-y-auto whitespace-pre-wrap text-sm text-gray-800 leading-relaxed">
                {transcriptRow.transcript || '(no transcript)'}
              </div>
            </div>
          </div>,
        )}

      <ConfirmModal
        isOpen={showDeleteImport}
        title="Delete call import?"
        description={(() => {
          const name = data.original_filename || '(unnamed)'
          const inFlight = data.status === 'pending' || data.status === 'processing'
          const lines = [
            `“${name}” will be permanently deleted, along with all ${data.total_rows} row record${data.total_rows === 1 ? '' : 's'} and ${data.completed_rows} stored recording${data.completed_rows === 1 ? '' : 's'} in S3.`,
            inFlight
              ? 'This batch is still processing — pending tasks will be revoked before deletion.'
              : '',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteImportMutation.isPending}
        onConfirm={() => deleteImportMutation.mutate(data.id)}
        onCancel={() => {
          if (deleteImportMutation.isPending) return
          setShowDeleteImport(false)
          setDeleteError(null)
        }}
      />

      <ConfirmModal
        isOpen={pendingDeleteRow !== null}
        title="Delete this recording?"
        description={(() => {
          if (!pendingDeleteRow) return ''
          const callId = pendingDeleteRow.external_call_id
          const hasS3 = !!pendingDeleteRow.recording_s3_key
          const lines = [
            `The row for CallID ${callId} will be removed from this import.`,
            hasS3
              ? 'The associated recording will also be deleted from S3.'
              : 'No recording is stored for this row yet, so only the row record will be removed.',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteRowMutation.isPending}
        onConfirm={() => {
          if (pendingDeleteRow && id) {
            deleteRowMutation.mutate({ importId: id, rowId: pendingDeleteRow.id })
          }
        }}
        onCancel={() => {
          if (deleteRowMutation.isPending) return
          setPendingDeleteRow(null)
          setDeleteError(null)
        }}
      />
    </div>
  )
}
