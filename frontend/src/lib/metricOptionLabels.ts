/** Align with app.services.metrics.option_labels (enum / classification labels). */

export function optionLabelFromRaw(opt: unknown): string | null {
  if (typeof opt === 'string') {
    const trimmed = opt.trim()
    return trimmed || null
  }
  if (typeof opt === 'number') {
    if (Number.isInteger(opt)) return String(opt)
    if (opt === Math.trunc(opt)) return String(Math.trunc(opt))
    return String(opt)
  }
  if (typeof opt === 'boolean') return String(opt)
  if (opt && typeof opt === 'object' && !Array.isArray(opt)) {
    const o = opt as Record<string, unknown>
    for (const key of ['value', 'label', 'name', 'description'] as const) {
      const nested = optionLabelFromRaw(o[key])
      if (nested) return nested
    }
  }
  return null
}

export function enumOptionsToCsv(options: unknown): string {
  if (!Array.isArray(options) || options.length === 0) return ''
  return options
    .map((opt) => optionLabelFromRaw(opt))
    .filter((label): label is string => Boolean(label))
    .join(', ')
}
