import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import { useBodyScrollLock } from '../../hooks/useBodyScrollLock'
import { prefetchCallRecordingQuery } from '../../lib/callRecordingQuery'
import {
  prefetchCallRecordingAudio,
  prefetchEvaluatorRecordingAudio,
} from '../../lib/waveformAudioCache'
import SyntheticCallTracePanel from './SyntheticCallTracePanel'
import ProviderCallTracePanel from './ProviderCallTracePanel'
import EvaluatorCallDetailPanel from './EvaluatorCallDetailPanel'
import ObservabilityCallDetailPanel from './ObservabilityCallDetailPanel'

export default function TraceDetailDrawer({
  open,
  onClose,
  traceId = null,
  evaluatorResultId = null,
  callShortId = null,
  observabilityCallShortId = null,
}: {
  open: boolean
  onClose: () => void
  traceId?: string | null
  evaluatorResultId?: string | null
  callShortId?: string | null
  observabilityCallShortId?: string | null
}) {
  const queryClient = useQueryClient()
  const hasContent = Boolean(traceId || evaluatorResultId || callShortId || observabilityCallShortId)
  useBodyScrollLock(open && hasContent)
  const ariaLabel = callShortId
    ? 'Provider call detail'
    : observabilityCallShortId
      ? 'Observability call detail'
      : evaluatorResultId
        ? 'Test agent call trace'
        : 'Call trace detail'

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    if (callShortId) {
      prefetchCallRecordingAudio(callShortId, false)
      void prefetchCallRecordingQuery(queryClient, callShortId)
    }
    if (observabilityCallShortId) {
      void queryClient.prefetchQuery({
        queryKey: ['observability-call', observabilityCallShortId],
        queryFn: () => apiClient.getObservabilityCall(observabilityCallShortId),
        staleTime: 30_000,
      })
    }
    if (evaluatorResultId) {
      prefetchEvaluatorRecordingAudio(evaluatorResultId)
      void queryClient.prefetchQuery({
        queryKey: ['evaluator-result', evaluatorResultId],
        queryFn: () => apiClient.getEvaluatorResult(evaluatorResultId, true),
        staleTime: 30_000,
      })
    }
  }, [open, callShortId, observabilityCallShortId, evaluatorResultId, queryClient])

  if (typeof document === 'undefined') return null

  return createPortal(
    <AnimatePresence>
      {open && hasContent && (
        <>
          <motion.button
            type="button"
            aria-label="Close detail drawer"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[100] bg-gray-900/45 backdrop-blur-[1px] overscroll-none touch-none"
            onClick={onClose}
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label={ariaLabel}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 32, stiffness: 320 }}
            className="fixed top-0 right-0 bottom-0 z-[101] flex h-[100dvh] w-full max-w-4xl flex-col overflow-hidden overscroll-contain border-l border-gray-200 bg-white shadow-2xl"
          >
            {callShortId ? (
              <ProviderCallTracePanel callShortId={callShortId} onClose={onClose} />
            ) : observabilityCallShortId ? (
              <ObservabilityCallDetailPanel
                callShortId={observabilityCallShortId}
                onClose={onClose}
              />
            ) : evaluatorResultId ? (
              <EvaluatorCallDetailPanel evaluatorResultId={evaluatorResultId} onClose={onClose} />
            ) : (
              <SyntheticCallTracePanel
                traceId={traceId ?? undefined}
                onClose={onClose}
                hideRecording
              />
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
  )
}
