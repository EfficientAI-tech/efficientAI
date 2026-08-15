export interface SingleMetricFormSnapshot {
  name: string
  description: string
  metric_type: 'number' | 'boolean' | 'rating' | 'text'
  custom_data_type: 'boolean' | 'enum' | 'number_range'
  enum_options_csv: string
  number_min: number
  number_max: number
  capture_rationale: boolean
}

const EXAMPLE_RATIONALE =
  'Brief justification referencing the transcript.'

const EXAMPLE_TEXT_VALUE =
  'A brief 1-3 sentence summary describing what was observed.'

const DEFAULT_ENUM_OPTIONS = ['Excellent', 'Good', 'Poor']

function parseEnumOptions(csv: string): string[] {
  return csv
    .split(',')
    .map((opt) => opt.trim())
    .filter(Boolean)
}

function exampleNumberValue(min: number, max: number): number {
  const lo = Number(min)
  const hi = Number(max)
  if (Number.isFinite(lo) && Number.isFinite(hi)) {
    return Math.round(((lo + hi) / 2) * 100) / 100
  }
  if (Number.isFinite(lo)) return lo
  return 5
}

function resolveStoredType(form: SingleMetricFormSnapshot): string {
  if (form.metric_type === 'text') return 'text'
  if (form.metric_type === 'boolean' || form.custom_data_type === 'boolean') {
    return 'boolean'
  }
  if (form.custom_data_type === 'enum' || form.metric_type === 'rating') {
    return 'enum'
  }
  return 'number'
}

function exampleValue(
  storedType: string,
  form: SingleMetricFormSnapshot,
  enumOptions: string[],
): unknown {
  if (storedType === 'text') return EXAMPLE_TEXT_VALUE
  if (storedType === 'boolean') return true
  if (storedType === 'enum') {
    return enumOptions[0] ?? DEFAULT_ENUM_OPTIONS[0]
  }
  return exampleNumberValue(form.number_min, form.number_max)
}

/**
 * Build a representative score entry matching what evaluation workers
 * persist under metric_scores[<metric_id>] for standalone metrics.
 */
export function buildSingleMetricValuePayload(
  form: SingleMetricFormSnapshot,
): Record<string, unknown> {
  const metricName = form.name.trim() || '(unnamed metric)'
  const storedType = resolveStoredType(form)
  const enumOptions =
    storedType === 'enum'
      ? (() => {
          const parsed = parseEnumOptions(form.enum_options_csv)
          return parsed.length > 0 ? parsed : [...DEFAULT_ENUM_OPTIONS]
        })()
      : []

  const payload: Record<string, unknown> = {
    value: exampleValue(storedType, form, enumOptions),
    type: storedType,
    metric_name: metricName,
    description: form.description.trim(),
  }

  if (storedType === 'enum') {
    payload.options = enumOptions
  }

  if (form.capture_rationale && form.metric_type !== 'text') {
    payload.rationale = EXAMPLE_RATIONALE
  }

  return payload
}

export function formatMetricValuePayloadJson(
  payload: Record<string, unknown>,
): string {
  return JSON.stringify(payload, null, 2)
}
