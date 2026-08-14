import type { ReactNode } from 'react'

/** Inline audit metadata for call imports and evaluations. */

export function formatMetaDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString()
}

type AuditMetaInlineItemProps = {
  label: string
  value: string | null | undefined
  /** `text-xs` for dense rows (evaluation list); default `text-sm` */
  dense?: boolean
  className?: string
}

export function AuditMetaChip({
  label,
  value,
  dense,
  className = '',
}: AuditMetaInlineItemProps) {
  const display = value?.trim() || '—'
  const sizeClass = dense ? 'text-xs' : 'text-sm'
  return (
    <span
      className={`inline-flex max-w-full min-w-0 flex-wrap items-baseline gap-x-1 ${sizeClass} ${className}`.trim()}
      title={display === '—' ? `${label}: unknown` : `${label}: ${display}`}
    >
      <span className="text-gray-500 shrink-0">{label}:</span>
      <span className="font-medium text-gray-800 break-all">{display}</span>
    </span>
  )
}

type AuditMetaRowProps = {
  className?: string
  dense?: boolean
  /** Join parent flex row (chips become siblings of status/provider). */
  inline?: boolean
  children: ReactNode
}

function AuditMetaRow({ className = '', dense, inline, children }: AuditMetaRowProps) {
  const textClass = dense ? 'text-xs' : 'text-sm'
  if (inline) {
    return <div className={`contents ${className}`.trim()}>{children}</div>
  }
  return (
    <div
      className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0 max-w-full text-gray-600 ${textClass} ${className}`.trim()}
    >
      {children}
    </div>
  )
}

type CallImportAuditMetaProps = {
  createdAt: string | null | undefined
  updatedAt: string | null | undefined
  createdByEmail?: string | null
  lastUpdatedByEmail?: string | null
  className?: string
  dense?: boolean
  inline?: boolean
}

/** Created / updated timestamps + actor emails for a call-import batch. */
export function CallImportAuditMeta({
  createdAt,
  updatedAt,
  createdByEmail,
  lastUpdatedByEmail,
  className,
  dense,
  inline,
}: CallImportAuditMetaProps) {
  return (
    <AuditMetaRow className={className} dense={dense} inline={inline}>
      <AuditMetaChip label="Created" value={formatMetaDateTime(createdAt)} dense={dense} />
      <AuditMetaChip label="Updated" value={formatMetaDateTime(updatedAt)} dense={dense} />
      <AuditMetaChip label="Created by" value={createdByEmail} dense={dense} />
      <AuditMetaChip label="Last updated by" value={lastUpdatedByEmail} dense={dense} />
    </AuditMetaRow>
  )
}

type EvaluationAuditMetaProps = {
  createdAt?: string | null | undefined
  updatedAt?: string | null | undefined
  startedAt?: string | null
  finishedAt?: string | null
  runByEmail?: string | null
  createdByEmail?: string | null
  lastUpdatedByEmail?: string | null
  formatDate?: (iso: string | null | undefined) => string
  className?: string
  dense?: boolean
  inline?: boolean
  showRunTimes?: boolean
  showTimestamps?: boolean
}

/** Evaluation run metadata (detail header or list card). */
export function EvaluationAuditMeta({
  createdAt,
  updatedAt,
  startedAt,
  finishedAt,
  runByEmail,
  createdByEmail,
  lastUpdatedByEmail,
  formatDate = formatMetaDateTime,
  className,
  dense,
  inline,
  showRunTimes = true,
  showTimestamps = false,
}: EvaluationAuditMetaProps) {
  const runner = runByEmail ?? createdByEmail
  return (
    <AuditMetaRow className={className} dense={dense} inline={inline}>
      <AuditMetaChip label="Run by" value={runner} dense={dense} />
      <AuditMetaChip label="Last updated by" value={lastUpdatedByEmail} dense={dense} />
      {showTimestamps && createdAt ? (
        <AuditMetaChip label="Created" value={formatDate(createdAt)} dense={dense} />
      ) : null}
      {showTimestamps && updatedAt ? (
        <AuditMetaChip label="Updated" value={formatDate(updatedAt)} dense={dense} />
      ) : null}
      {showRunTimes && startedAt ? (
        <AuditMetaChip label="Started" value={formatDate(startedAt)} dense={dense} />
      ) : null}
      {showRunTimes && finishedAt ? (
        <AuditMetaChip label="Finished" value={formatDate(finishedAt)} dense={dense} />
      ) : null}
    </AuditMetaRow>
  )
}
