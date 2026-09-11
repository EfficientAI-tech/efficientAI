import Button from './Button'

export default function TableListPagination({
  page,
  pageCount,
  total,
  pageSize,
  onPrev,
  onNext,
}: {
  page: number
  pageCount: number
  total: number
  pageSize: number
  onPrev: () => void
  onNext: () => void
}) {
  if (pageCount <= 1 || total === 0) return null

  const start = (page - 1) * pageSize + 1
  const end = Math.min(total, page * pageSize)

  return (
    <div className="flex items-center justify-between border-t border-gray-200 px-4 py-4 text-sm">
      <p className="text-gray-500">
        Showing {start}–{end} of {total} · Page {page} of {pageCount}
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={onPrev}>
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={page >= pageCount} onClick={onNext}>
          Next
        </Button>
      </div>
    </div>
  )
}
