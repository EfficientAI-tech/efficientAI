/**
 * Shared pagination bar used at the top and bottom of large lists in
 * the Call Imports section (and elsewhere). Renders three pieces:
 *
 *  1. A "Showing X–Y of Z" range string when ``total`` + ``pageSize``
 *     are provided. When ``rangeLabelOverride`` is set, that string is
 *     used instead — handy when the parent already has a richer
 *     filter-aware label (e.g. "1–50 of 200 matching").
 *  2. A "Page N of M" indicator.
 *  3. Prev / Next buttons with the same chevron icons + ghost-button
 *     styling the inline implementations used to ship.
 *
 * The component is **headless** about state — the parent owns the
 * current page and passes ``onPrev`` / ``onNext`` callbacks. This
 * keeps the existing offset-based (CallImportDetail) and
 * page-number-based (CallImportEvaluationDetail) pagers compatible
 * without forcing both onto a single state shape.
 *
 * Renders nothing when ``pageCount <= 1`` so callers don't have to
 * guard the component at every call site — drop it in, the bar
 * disappears once there's only one page of results.
 *
 * Designed to be safely placed in both the top and bottom of a list:
 * pass distinct ``variant`` values if you want subtle styling
 * differences (margins, border position); the default ``inline``
 * variant has no outer chrome so the parent can nest it inside a
 * surrounding card without double-borders.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react'

import Button from './Button'

export interface PaginationProps {
  /** 1-based page index of the currently-rendered slice. */
  page: number
  /** Total number of pages. The bar hides itself when this is ≤ 1. */
  pageCount: number
  /**
   * Optional total row count + page size. When both are supplied we
   * render a "Showing X–Y of Z" label; when either is missing we
   * fall back to "Page N of M" only.
   */
  total?: number
  pageSize?: number
  onPrev: () => void
  onNext: () => void
  /**
   * Layout flavour:
   *  - ``inline`` (default): no card chrome. Drop in next to a
   *    toolbar or above a table.
   *  - ``card``: gray-50 card with a top/bottom border, matching the
   *    legacy inline bar at the bottom of CallImportDetail's rows
   *    tab.
   */
  variant?: 'inline' | 'card'
  /**
   * When provided, this string replaces the auto-computed
   * "Showing X–Y of Z" label. Use this when a parent has a more
   * accurate filter-aware label.
   */
  rangeLabelOverride?: string
  /**
   * Extra className applied to the outermost element. Useful for
   * spacing tweaks per call site.
   */
  className?: string
  /** Optional disabled toggle (e.g. while a row mutation is pending). */
  disabled?: boolean
}

export default function Pagination({
  page,
  pageCount,
  total,
  pageSize,
  onPrev,
  onNext,
  variant = 'inline',
  rangeLabelOverride,
  className,
  disabled = false,
}: PaginationProps) {
  if (pageCount <= 1) return null

  // Compute the "Showing X–Y of Z" label when total + pageSize are
  // available. Falls back to the simpler "Page N of M" otherwise.
  let rangeLabel: string
  if (rangeLabelOverride !== undefined) {
    rangeLabel = rangeLabelOverride
  } else if (
    typeof total === 'number' &&
    typeof pageSize === 'number' &&
    pageSize > 0
  ) {
    const start = total === 0 ? 0 : (page - 1) * pageSize + 1
    const end = Math.min(total, page * pageSize)
    rangeLabel = `Showing ${start}–${end} of ${total} · Page ${page} of ${pageCount}`
  } else {
    rangeLabel = `Page ${page} of ${pageCount}`
  }

  const wrapperClass =
    variant === 'card'
      ? `px-4 py-3 bg-gray-50 border border-gray-200 rounded-lg flex items-center justify-between ${
          className ?? ''
        }`
      : `flex items-center justify-between ${className ?? ''}`

  const atFirstPage = page <= 1 || disabled
  const atLastPage = page >= pageCount || disabled

  return (
    <div className={wrapperClass}>
      <p className="text-sm text-gray-600">{rangeLabel}</p>
      <div className="flex gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={onPrev}
          disabled={atFirstPage}
          leftIcon={<ChevronLeft className="h-4 w-4" />}
        >
          Prev
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onNext}
          disabled={atLastPage}
          rightIcon={<ChevronRight className="h-4 w-4" />}
        >
          Next
        </Button>
      </div>
    </div>
  )
}
