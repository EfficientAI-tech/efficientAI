function UserInsightsTranscriptSourceSelect({
  value,
  onChange,
  disabled = false,
}: {
  value: 'diarised' | 'production'
  onChange: (value: 'diarised' | 'production') => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-[11px] text-gray-600">
      <span className="font-medium text-gray-700">Insights transcript source</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as 'diarised' | 'production')}
        className="text-[11px] border border-gray-200 rounded-md bg-white px-2 py-1 text-gray-700 focus:outline-none focus:ring-1 focus:ring-primary-300"
        title="Which transcript text is sent to the user-insights LLM"
      >
        <option value="diarised">Diarised (default)</option>
        <option value="production">Production / raw</option>
      </select>
    </label>
  )
}

export { UserInsightsTranscriptSourceSelect }
