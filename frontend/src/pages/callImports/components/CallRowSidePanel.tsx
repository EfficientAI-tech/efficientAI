import { useEffect, type ReactNode } from 'react'
import { AlertCircle, ExternalLink, RefreshCw, X } from 'lucide-react'

import RecordingAudioPlayer from '../../../components/audio/RecordingAudioPlayer'
import { useRecordingPresignedUrl } from '../../../hooks/useRecordingPresignedUrl'

export interface CallRowSidePanelTab {
  id: string
  label: string
  /** Small hint beside the tab label (e.g. "Scored"). */
  hint?: string
}

export interface CallRowSidePanelProps {
  onClose: () => void
  /** Primary identifier shown in the header (conversation id). */
  title: string
  headerMeta?: ReactNode
  errorBanner?: ReactNode
  recordingS3Key?: string | null
  recordingUrl?: string | null
  tabs: CallRowSidePanelTab[]
  activeTab: string
  onTabChange: (tabId: string) => void
  children: ReactNode
  className?: string
}

/**
 * Call-detail panel for the right column in {@link CallRowDetailSplitLayout}.
 * Fills the pinned column height; only the list scrolls beside it.
 */
export function CallRowSidePanel({
  onClose,
  title,
  headerMeta,
  errorBanner,
  recordingS3Key,
  recordingUrl,
  tabs,
  activeTab,
  onTabChange,
  children,
  className = '',
}: CallRowSidePanelProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const {
    data: presignedRecording,
    isLoading: presignedLoading,
    isError: presignedError,
  } = useRecordingPresignedUrl(recordingS3Key || null)

  const playbackUrl = presignedRecording?.url || null

  return (
    <aside
      className={`flex flex-col h-full min-h-0 rounded-lg border border-gray-200 bg-white shadow-lg overflow-hidden ${className}`}
      aria-label="Call row details"
      role="complementary"
    >
      <div className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wider text-gray-500">Call details</p>
          <p className="text-base font-semibold text-gray-900 font-mono truncate" title={title}>
            {title}
          </p>
          {headerMeta ? <div className="mt-1.5 flex flex-wrap items-center gap-2">{headerMeta}</div> : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1.5 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 shrink-0"
          aria-label="Close panel"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
        <div className="px-4 py-4 space-y-4">
          {errorBanner}

          <RecordingSection
            recordingS3Key={recordingS3Key}
            recordingUrl={recordingUrl}
            presignedLoading={presignedLoading}
            presignedError={presignedError}
            playbackUrl={playbackUrl}
          />

          {tabs.length > 0 ? (
            <>
              <div className="border-b border-gray-100 flex items-center gap-0 flex-wrap sticky top-0 bg-white z-[1] pb-px">
                {tabs.map((tab) => {
                  const active = activeTab === tab.id
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => onTabChange(tab.id)}
                      className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors -mb-px inline-flex items-center gap-1.5 ${
                        active
                          ? 'border-primary-600 text-primary-700'
                          : 'border-transparent text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      {tab.label}
                      {tab.hint ? (
                        <span className="text-[10px] font-normal text-primary-600/80">{tab.hint}</span>
                      ) : null}
                    </button>
                  )
                })}
              </div>
              <div>{children}</div>
            </>
          ) : (
            children
          )}
        </div>
      </div>
    </aside>
  )
}

function RecordingSection({
  recordingS3Key,
  recordingUrl,
  presignedLoading,
  presignedError,
  playbackUrl,
}: {
  recordingS3Key?: string | null
  recordingUrl?: string | null
  presignedLoading: boolean
  presignedError: boolean
  playbackUrl: string | null
}) {
  if (recordingS3Key) {
    if (presignedLoading && !playbackUrl) {
      return (
        <div className="text-xs text-gray-500 inline-flex items-center gap-2">
          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          Loading audio…
        </div>
      )
    }
    if (presignedError || !playbackUrl) {
      return (
        <div className="text-xs text-red-700 inline-flex items-center gap-2">
          <AlertCircle className="h-3.5 w-3.5" />
          Could not load recording from storage.
        </div>
      )
    }
    return (
      <RecordingAudioPlayer src={playbackUrl} downloadUrl={playbackUrl} />
    )
  }

  if (recordingUrl) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
        <p className="mb-1">Recording has not been downloaded to storage yet.</p>
        <a
          href={recordingUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-700 font-medium"
        >
          Open source URL in new tab
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    )
  }

  return (
    <p className="text-xs text-gray-400 italic">No recording available for this row.</p>
  )
}
