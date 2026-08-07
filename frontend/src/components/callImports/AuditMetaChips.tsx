import type { ReactNode } from 'react'

/** Bordered metadata chips for call-import audit fields. */

const CHIP_CLASS =
  'inline-flex flex-col min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] leading-tight shadow-sm'

export function formatMetaDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString()
}

type AuditMetaChipProps = {
  label: string
  value: string | null | undefined
  wide?: boolean
  /** Tighter chip for horizontal list rows */
  dense?: boolean
  /** Fill a grid cell (2×2 activity column on list page) */
  stacked?: boolean
  className?: string
}

export function AuditMetaChip({
  label,
  value,
  wide,
  dense,
  stacked,
  className = '',
}: AuditMetaChipProps) {
  const display = value?.trim() || '—'
  const sizeClass = dense
    ? stacked
      ? 'w-full min-w-0 px-1.5 py-0.5 text-[10px]'
      : 'shrink-0 px-1.5 py-0.5 text-[10px] min-w-[4.75rem] max-w-[8.5rem]'
    : wide
      ? 'min-w-[7.5rem] max-w-[12rem]'
      : 'min-w-[6.5rem] max-w-[10rem]'
  return (
    <div
      className={`${CHIP_CLASS} ${sizeClass} ${className}`.trim()}
      title={display === '—' ? `${label}: unknown` : `${label}: ${display}`}
    >
      <span className="text-gray-500 font-medium">{label}</span>
      <span className="text-gray-800 truncate font-medium">{display}</span>
    </div>
  )
}

type AuditMetaChipRowProps = {
  className?: string
  wide?: boolean
  compact?: boolean
  children: ReactNode
}

function AuditMetaChipRow({
  className = '',
  wide,
  compact,
  children,
}: AuditMetaChipRowProps) {
  return (
    <div
      className={
        compact
          ? `flex flex-nowrap items-stretch gap-1.5 overflow-x-auto max-w-full scrollbar-thin ${className}`.trim()
          : `flex flex-wrap items-stretch gap-1.5 ${className}`.trim()
      }
      data-wide={wide ? 'true' : undefined}
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
  wide?: boolean
  compact?: boolean
  /** 2×2 grid for table cells (no horizontal scroll) */
  stacked?: boolean
}

/** Created / updated timestamps + actor emails for a call-import batch. */
export function CallImportAuditMeta({
  createdAt,
  updatedAt,
  createdByEmail,
  lastUpdatedByEmail,
  className,
  wide = true,
  compact,
  stacked,
}: CallImportAuditMetaProps) {
  const chipCommon = { wide, dense: compact, stacked }
  if (stacked) {
    return (
      <div
        className={`grid grid-cols-2 gap-1.5 w-full min-w-[12rem] max-w-[22rem] ${className ?? ''}`.trim()}
      >
        <AuditMetaChip label="Created" value={formatMetaDateTime(createdAt)} {...chipCommon} />
        <AuditMetaChip label="Updated" value={formatMetaDateTime(updatedAt)} {...chipCommon} />
        <AuditMetaChip label="Created by" value={createdByEmail} {...chipCommon} />
        <AuditMetaChip label="Last updated by" value={lastUpdatedByEmail} {...chipCommon} />
      </div>
    )
  }
  return (
    <AuditMetaChipRow className={className} wide={wide} compact={compact}>
      <AuditMetaChip label="Created" value={formatMetaDateTime(createdAt)} wide={wide} dense={compact} />
      <AuditMetaChip label="Updated" value={formatMetaDateTime(updatedAt)} wide={wide} dense={compact} />
      <AuditMetaChip label="Created by" value={createdByEmail} wide={wide} dense={compact} />
      <AuditMetaChip label="Last updated by" value={lastUpdatedByEmail} wide={wide} dense={compact} />
    </AuditMetaChipRow>
  )
}

type EvaluationAuditMetaProps = {
  createdAt: string | null | undefined
  updatedAt?: string | null | undefined
  startedAt?: string | null
  finishedAt?: string | null
  /** User who started this evaluation run (API: created_by_email). */
  runByEmail?: string | null
  /** @deprecated Use runByEmail */
  createdByEmail?: string | null
  lastUpdatedByEmail?: string | null
  formatDate?: (iso: string | null | undefined) => string
  className?: string
  wide?: boolean
  compact?: boolean
  showRunTimes?: boolean
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
  wide = true,
  compact,
  showRunTimes = true,
}: EvaluationAuditMetaProps) {
  const runner = runByEmail ?? createdByEmail
  return (
    <AuditMetaChipRow className={className} wide={wide} compact={compact}>
      <AuditMetaChip label="Run by" value={runner} wide={wide} dense={compact} />
      <AuditMetaChip label="Last updated by" value={lastUpdatedByEmail} wide={wide} dense={compact} />
      <AuditMetaChip label="Created" value={formatDate(createdAt)} wide={wide} dense={compact} />
      {updatedAt ? (
        <AuditMetaChip label="Updated" value={formatDate(updatedAt)} wide={wide} dense={compact} />
      ) : null}
      {showRunTimes && startedAt ? (
        <AuditMetaChip label="Started" value={formatDate(startedAt)} wide={wide} dense={compact} />
      ) : null}
      {showRunTimes && finishedAt ? (
        <AuditMetaChip label="Finished" value={formatDate(finishedAt)} wide={wide} dense={compact} />
      ) : null}
    </AuditMetaChipRow>
  )
}
