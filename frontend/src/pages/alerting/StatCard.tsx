type StatCardProps = {
  label: string
  value: number | string
  hint?: string
  tone?: 'default' | 'success' | 'warning' | 'danger'
}

const toneClasses = {
  default: 'border-gray-200 bg-white text-gray-900',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  danger: 'border-red-200 bg-red-50 text-red-900',
}

export default function StatCard({ label, value, hint, tone = 'default' }: StatCardProps) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClasses[tone]}`}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-xs text-gray-400">{hint}</div>}
    </div>
  )
}
