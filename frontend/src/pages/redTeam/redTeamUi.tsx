import { AlertTriangle, Ban, CheckCircle2, CircleDashed, HelpCircle, Loader2, ShieldAlert, ShieldCheck, XCircle } from 'lucide-react'
import type { RedTeamAttack, RedTeamCategoryStatus, RedTeamRunStatus, RedTeamVerdict } from '../../types/redTeam'
import { isRedTeamRunActive } from './redTeamFormat'

const STATUS_STYLES: Record<RedTeamRunStatus, { label: string; className: string }> = {
  queued: { label: 'Queued', className: 'bg-gray-100 text-gray-700' },
  recon: { label: 'Recon', className: 'bg-primary-50 text-primary-800' },
  attacking: { label: 'Attacking', className: 'bg-primary-100 text-primary-800' },
  reporting: { label: 'Reporting', className: 'bg-primary-100 text-primary-800' },
  completed: { label: 'Completed', className: 'bg-green-50 text-green-700' },
  failed: { label: 'Failed', className: 'bg-red-50 text-red-700' },
  cancelled: { label: 'Cancelled', className: 'bg-gray-100 text-gray-600' },
}

export function RedTeamStatusChip({ status }: { status: RedTeamRunStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.queued
  const Icon =
    status === 'completed'
      ? CheckCircle2
      : status === 'failed'
        ? XCircle
        : status === 'cancelled'
          ? Ban
          : status === 'queued'
            ? CircleDashed
            : Loader2
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${style.className}`}>
      <Icon className={`h-3.5 w-3.5 ${isRedTeamRunActive(status) && status !== 'queued' ? 'animate-spin' : ''}`} />
      {style.label}
    </span>
  )
}

const VERDICT_STYLES: Record<RedTeamVerdict, { label: string; className: string; Icon: typeof ShieldAlert }> = {
  breached: { label: 'Breached', className: 'border-red-200 bg-red-50 text-red-700', Icon: ShieldAlert },
  held_under_pressure: {
    label: 'Held under pressure',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
    Icon: AlertTriangle,
  },
  held: { label: 'Held', className: 'border-green-200 bg-green-50 text-green-700', Icon: ShieldCheck },
  inconclusive: { label: 'Inconclusive', className: 'border-gray-200 bg-gray-50 text-gray-600', Icon: HelpCircle },
}

export function VerdictBadge({ verdict, size = 'sm' }: { verdict: RedTeamVerdict | null; size?: 'sm' | 'lg' }) {
  if (!verdict) return <span className="text-xs text-gray-400">—</span>
  const style = VERDICT_STYLES[verdict] ?? VERDICT_STYLES.inconclusive
  const sizing = size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border font-medium ${sizing} ${style.className}`}>
      <style.Icon className={size === 'lg' ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
      {style.label}
    </span>
  )
}

/** Live state while running, else the judge outcome. Icon + label, never color alone. */
export function AttackOutcomeChip({ attack }: { attack: Pick<RedTeamAttack, 'status' | 'outcome'> }) {
  const base = 'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium'
  if (attack.status === 'running' || attack.status === 'evaluating') {
    return (
      <span className={`${base} bg-primary-50 text-primary-800`}>
        <Loader2 className="h-3 w-3 animate-spin" />
        {attack.status === 'running' ? 'Running' : 'Evaluating'}
      </span>
    )
  }
  if (attack.status === 'queued') {
    return (
      <span className={`${base} bg-gray-100 text-gray-600`}>
        <CircleDashed className="h-3 w-3" /> Queued
      </span>
    )
  }
  if (attack.status === 'cancelled') {
    return (
      <span className={`${base} bg-gray-100 text-gray-600`}>
        <Ban className="h-3 w-3" /> Cancelled
      </span>
    )
  }
  switch (attack.outcome) {
    case 'breached':
      return (
        <span className={`${base} bg-red-50 text-red-700`}>
          <ShieldAlert className="h-3 w-3" /> Breached
        </span>
      )
    case 'conceded':
      return (
        <span className={`${base} bg-amber-50 text-amber-800`}>
          <AlertTriangle className="h-3 w-3" /> Conceded
        </span>
      )
    case 'held':
      return (
        <span className={`${base} bg-green-50 text-green-700`}>
          <ShieldCheck className="h-3 w-3" /> Held
        </span>
      )
    default:
      return (
        <span className={`${base} bg-gray-100 text-gray-600`}>
          <XCircle className="h-3 w-3" /> {attack.status === 'failed' || attack.outcome === 'error' ? 'Error' : 'Done'}
        </span>
      )
  }
}

const CATEGORY_STATUS_STYLES: Record<RedTeamCategoryStatus, { label: string; className: string }> = {
  FAIL: { label: 'Fail', className: 'bg-red-50 text-red-700 border-red-200' },
  PARTIAL: { label: 'Partial', className: 'bg-amber-50 text-amber-800 border-amber-200' },
  PASS: { label: 'Pass', className: 'bg-green-50 text-green-700 border-green-200' },
  NOT_TESTED: { label: 'Not tested', className: 'bg-gray-50 text-gray-500 border-gray-200' },
}

export function CategoryStatusChip({ status }: { status: RedTeamCategoryStatus }) {
  const style = CATEGORY_STATUS_STYLES[status] ?? CATEGORY_STATUS_STYLES.NOT_TESTED
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-semibold uppercase ${style.className}`}>
      {style.label}
    </span>
  )
}
