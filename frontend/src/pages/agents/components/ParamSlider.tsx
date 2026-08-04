function ParamSlider({
  label,
  helpText,
  min,
  max,
  step,
  integer,
  value,
  onChange,
  disabled,
}: {
  label: string
  helpText?: string
  min: number
  max: number
  step: number
  integer?: boolean
  value: number | null | undefined
  onChange: (next: number | null) => void
  disabled?: boolean
}) {
  const numeric = value ?? min
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label className="text-sm font-medium text-gray-800">{label}</label>
        <input
          type="number"
          disabled={disabled}
          min={min}
          max={max}
          step={step}
          value={value ?? ''}
          placeholder="Default"
          onChange={(e) => {
            const raw = e.target.value
            if (raw === '') {
              onChange(null)
              return
            }
            onChange(integer ? parseInt(raw, 10) : parseFloat(raw))
          }}
          className="w-20 px-2 py-1 text-sm border border-gray-300 rounded-md text-right focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-50"
        />
      </div>
      <input
        type="range"
        disabled={disabled}
        min={min}
        max={max}
        step={step}
        value={numeric}
        onChange={(e) =>
          onChange(integer ? parseInt(e.target.value, 10) : parseFloat(e.target.value))
        }
        className="w-full h-2 rounded-full appearance-none bg-gray-200 accent-primary-600 disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary-600 [&::-webkit-slider-thumb]:shadow-md"
      />
      {helpText ? <p className="text-xs text-gray-500">{helpText}</p> : null}
    </div>
  )
}

export default ParamSlider
