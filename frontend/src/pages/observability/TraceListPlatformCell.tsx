import { traceListPlatformSummary, type TraceListModality } from '../../lib/traceListLabels'

const MODALITY_STYLES: Record<TraceListModality, string> = {
  chat: 'border-sky-200 bg-sky-50 text-sky-900',
  voice: 'border-gray-200 bg-gray-50 text-gray-700',
}

export function TraceListPlatformCell({
  sessionModality,
  transport,
}: {
  sessionModality?: 'chat' | 'voice' | null
  transport?: string | null
}) {
  const { modality, detail } = traceListPlatformSummary(sessionModality, transport)
  const label = modality === 'chat' ? 'Chat' : 'Voice'
  return (
    <div className="flex flex-col gap-1">
      <span
        className={`inline-flex w-fit rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${MODALITY_STYLES[modality]}`}
      >
        {label}
      </span>
      {detail ? <span className="text-xs text-gray-600">{detail}</span> : null}
    </div>
  )
}