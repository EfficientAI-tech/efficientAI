import { type ReactNode } from 'react'
import { Globe, PhoneIncoming, PhoneOutgoing, type LucideIcon } from 'lucide-react'

export const MODERN_INPUT_CLASS =
  'w-full rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 disabled:bg-gray-50 disabled:text-gray-500'

export const MODERN_SELECT_CLASS =
  'w-full rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 shadow-sm transition focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20'

export interface CallTypeConfig {
  label: string
  icon: LucideIcon
  bg: string
  text: string
  border: string
}

export function getCallTypeConfig(
  medium?: string | null,
  callType?: string | null,
): CallTypeConfig {
  if (medium === 'web_call') {
    return {
      label: 'Web',
      icon: Globe,
      bg: 'bg-indigo-50',
      text: 'text-indigo-700',
      border: 'border-indigo-100',
    }
  }
  if (callType === 'inbound') {
    return {
      label: 'Phone inbound',
      icon: PhoneIncoming,
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-100',
    }
  }
  return {
    label: 'Phone outbound',
    icon: PhoneOutgoing,
    bg: 'bg-emerald-50',
    text: 'text-emerald-700',
    border: 'border-emerald-100',
  }
}

export function CallTypeBadge({
  medium,
  callType,
}: {
  medium?: string | null
  callType?: string | null
}) {
  const cfg = getCallTypeConfig(medium, callType)
  const Icon = cfg.icon
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${cfg.bg} ${cfg.text} ${cfg.border}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {cfg.label}
    </span>
  )
}

export function StatCard({
  label,
  value,
  icon,
  accentClass = 'text-gray-900',
  iconBgClass = 'bg-slate-100',
  iconClass = 'text-slate-600',
}: {
  label: string
  value: string | number
  icon: ReactNode
  accentClass?: string
  iconBgClass?: string
  iconClass?: string
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</p>
          <p className={`text-2xl font-bold mt-1 ${accentClass}`}>{value}</p>
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${iconBgClass}`}>
          <span className={iconClass}>{icon}</span>
        </div>
      </div>
    </div>
  )
}
