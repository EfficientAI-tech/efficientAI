import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

export const AGENT_LANGUAGE_LABELS: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  de: 'German',
  zh: 'Chinese',
  hi: 'Hindi',
}

export function OverviewSection({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-gray-200/90 bg-white shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-gray-50/80 to-white">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        {description ? <p className="text-xs text-gray-500 mt-0.5">{description}</p> : null}
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}

export function OverviewStatCard({
  icon: Icon,
  label,
  value,
  accent = 'gray',
}: {
  icon: LucideIcon
  label: string
  value: ReactNode
  accent?: 'gray' | 'primary' | 'emerald' | 'violet'
}) {
  const accentClasses = {
    gray: 'bg-gray-100 text-gray-600',
    primary: 'bg-primary-50 text-primary-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    violet: 'bg-violet-50 text-violet-600',
  }[accent]

  return (
    <div className="flex gap-3 rounded-lg border border-gray-100 bg-gray-50/40 p-4 transition-colors hover:border-gray-200/80 hover:bg-white">
      <div
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${accentClasses}`}
      >
        <Icon className="h-5 w-5" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-gray-500">{label}</p>
        <p className="mt-0.5 text-sm font-semibold text-gray-900 truncate">{value}</p>
      </div>
    </div>
  )
}

export function formatSilenceHangupLabel(secs: number | null | undefined): string {
  const value = secs ?? 15
  if (value === 0) return 'Disabled'
  return value === 1 ? '1 second' : `${value} seconds`
}

export const OVERVIEW_NOT_CONFIGURED = (
  <span className="text-gray-400 font-normal italic">Not configured</span>
)

export function OverviewConfigBadge({ configured }: { configured: boolean }) {
  return configured ? (
    <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-200/90">
      Configured
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-semibold text-gray-600 ring-1 ring-gray-200/90">
      Not configured
    </span>
  )
}

export function OverviewDetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-[minmax(8rem,38%)_1fr] gap-1 sm:gap-4 py-3 border-b border-gray-100 last:border-0 last:pb-0 first:pt-0">
      <dt className="text-xs font-medium text-gray-500">{label}</dt>
      <dd className="text-sm font-semibold text-gray-900 sm:text-right break-words">{value}</dd>
    </div>
  )
}
