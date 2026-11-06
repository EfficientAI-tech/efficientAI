import { X } from 'lucide-react'

export default function FilterChip({
  label,
  onClear,
}: {
  label: string
  onClear: () => void
}) {
  return (
    <span className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-full bg-primary-50 text-primary-700 border border-primary-200">
      <span className="font-medium">{label}</span>
      <button
        type="button"
        onClick={onClear}
        className="rounded-full p-0.5 hover:bg-primary-100"
        aria-label={`Clear filter ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  )
}
