const INPUT_CLASS =
  'w-full rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 disabled:bg-gray-50 disabled:text-gray-500'

type Props = {
  value: string
  onChange: (value: string) => void
  className?: string
}

export default function MetricTagsField({ value, onChange, className }: Props) {
  return (
    <div className={className}>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Tags (comma separated)
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={INPUT_CLASS}
        placeholder="quality, compliance, friendliness"
      />
    </div>
  )
}
