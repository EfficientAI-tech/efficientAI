import { USER_INSIGHTS_SAMPLE_SIZE_OPTIONS } from './userInsightsConstants'

function UserInsightsSampleSizeSelect({
  value,
  onChange,
  disabled = false,
}: {
  value: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-[11px] text-gray-600">
      <span className="font-medium text-gray-700">
        User insights sample size
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="text-[11px] border border-gray-200 rounded-md bg-white px-2 py-1 text-gray-700 focus:outline-none focus:ring-1 focus:ring-primary-300"
        title="Maximum LLM calls used to sample calls for user insights"
      >
        {USER_INSIGHTS_SAMPLE_SIZE_OPTIONS.map((size) => (
          <option key={size} value={size}>
            {size} LLM calls
          </option>
        ))}
      </select>
    </label>
  )
}

export { UserInsightsSampleSizeSelect }
