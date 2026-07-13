/** Inline pill showing upstream diarisation progress for a call-import row. */
export default function DiariseStatusPill({
  status,
}: {
  status?: string | null
}) {
  if (!status || status === 'idle') return null
  const tone =
    status === 'failed'
      ? 'bg-red-100 text-red-700 border-red-200'
      : status === 'completed'
        ? 'bg-green-100 text-green-700 border-green-200'
        : status === 'running'
          ? 'bg-blue-100 text-blue-700 border-blue-200'
          : 'bg-gray-100 text-gray-700 border-gray-200'
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${tone}`}
      title={`Diarisation: ${status}`}
    >
      Diarise: {status}
    </span>
  )
}
