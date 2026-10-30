export type JevQuestionBlock = {
  type?: string
  value?: unknown
  noul?: unknown
  choice?: unknown
  score?: unknown
  probabilities?: Record<string, unknown>
  options?: Record<string, unknown>
  legend?: Record<string, unknown>
  confidence?: unknown
  confidence_threshold?: unknown
  needs_review?: boolean
  review_reason?: string
  error?: string
}

export type JevReviewState = {
  resolved?: boolean
  resolved_by?: string | null
  resolved_at?: string
  resolved_value?: unknown
  original_value?: unknown
}

export type JevScore = {
  type?: string
  jev_type?: string
  metric_name?: string
  value?: unknown
  noul?: unknown
  needs_review?: boolean
  review_reason?: string
  questions?: Record<string, JevQuestionBlock>
  review?: JevReviewState
  error?: string
  confidence?: unknown
  probabilities?: Record<string, unknown>
  legend?: Record<string, unknown>
}

export function isJevScore(score: unknown): score is JevScore {
  return Boolean(score && typeof score === 'object' && (score as JevScore).type === 'jev')
}

export function jevNeedsReview(score: unknown): boolean {
  if (!isJevScore(score)) return false
  if (score.review?.resolved) return false
  if (score.needs_review) return true
  const questions = score.questions || {}
  return Object.entries(questions).some(
    ([key, block]) =>
      (key === 'choice' || key === 'score') && Boolean(block?.needs_review),
  )
}

function formatNoul(noul: unknown, value: unknown): string {
  const numeric = typeof noul === 'number' ? noul : Number(noul)
  const yes =
    typeof value === 'boolean'
      ? value
      : Number.isFinite(numeric)
        ? numeric >= 0.5
        : Boolean(value)
  const label = yes ? 'Yes' : 'No'
  if (Number.isFinite(numeric)) return `${label} (${numeric.toFixed(2)})`
  return label
}

export function formatJevCell(score: unknown): string {
  if (!isJevScore(score)) return '—'
  if (score.review?.resolved && score.review.resolved_value != null) {
    const resolved = score.review.resolved_value
    if (typeof resolved === 'boolean') {
      return resolved ? 'Yes' : 'No'
    }
    return String(resolved)
  }
  const questions = score.questions || {}
  const parts: string[] = []
  if (questions.noul && questions.noul.value != null) {
    parts.push(formatNoul(questions.noul.noul, questions.noul.value))
  } else if (score.jev_type === 'noul' && (score.noul != null || typeof score.value === 'boolean' || typeof score.value === 'number')) {
    parts.push(formatNoul(score.noul ?? score.value, score.value))
  }
  if (questions.choice?.value != null && questions.choice.value !== '') {
    parts.push(String(questions.choice.value))
  }
  if (questions.score?.value != null && questions.score.value !== '') {
    parts.push(String(questions.score.value))
  }
  if (parts.length > 0) return parts.join(' · ')
  if (score.value == null || score.value === '') return '—'
  if (typeof score.value === 'boolean') {
    return formatNoul(score.noul, score.value)
  }
  if (typeof score.value === 'number' && score.jev_type === 'noul') {
    return formatNoul(score.value, score.value)
  }
  return String(score.value)
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function jevQuestionBlock(
  score: JevScore,
  typ: 'noul' | 'choice' | 'score',
): JevQuestionBlock | undefined {
  const fromMap = score.questions?.[typ]
  if (fromMap) return fromMap
  if (score.jev_type === typ) {
    return score as JevQuestionBlock
  }
  return undefined
}

export function jevResponseJson(
  score: JevScore,
  typ: 'noul' | 'choice' | 'score',
): Record<string, unknown> {
  const block = jevQuestionBlock(score, typ) || {}
  if (typ === 'noul') {
    return {
      type: 'noul',
      noul: block.noul ?? score.noul ?? null,
      value: block.value ?? (typeof score.value === 'boolean' ? score.value : null),
    }
  }
  if (typ === 'choice') {
    const payload: Record<string, unknown> = {
      type: 'choice',
      choice: block.choice ?? block.value ?? null,
      value: block.value ?? block.choice ?? null,
    }
    const probabilities = (block.probabilities || score.probabilities || {}) as Record<
      string,
      unknown
    >
    const optionKeys = Object.keys(block.options || {})
    const keys = optionKeys.length > 0 ? optionKeys : Object.keys(probabilities)
    if (keys.length > 0) {
      payload.probabilities = Object.fromEntries(
        keys.map((key) => [key, probabilities[key] ?? null]),
      )
    }
    const confidence = block.confidence ?? score.confidence
    if (confidence != null) payload.confidence = confidence
    return payload
  }
  const payload: Record<string, unknown> = {
    type: 'score',
    score: block.score ?? null,
    value: block.value ?? null,
  }
  const legend = block.legend || score.legend
  if (legend && Object.keys(legend).length > 0) payload.legend = legend
  const probabilities = (block.probabilities || score.probabilities || {}) as Record<
    string,
    unknown
  >
  const legendKeys = Object.keys(legend || {})
  const keys = legendKeys.length > 0 ? legendKeys : Object.keys(probabilities)
  if (keys.length > 0) {
    payload.probabilities = Object.fromEntries(
      keys.map((key) => [key, probabilities[key] ?? null]),
    )
  }
  const confidence = block.confidence ?? score.confidence
  if (confidence != null) payload.confidence = confidence
  return payload
}

export function jevProbabilityRows(
  block: JevQuestionBlock | undefined,
  selected?: unknown,
): Array<{ key: string; label: string; probability: number | null; selected: boolean }> {
  const probabilities = block?.probabilities || {}
  const legend = block?.legend || {}
  const options = block?.options || {}
  const keys = new Set([
    ...Object.keys(options),
    ...Object.keys(probabilities),
    ...Object.keys(legend),
  ])
  const selectedText = selected == null ? '' : String(selected)
  return [...keys].map((key) => {
    const label = legend[key] != null ? String(legend[key]) : key
    return {
      key,
      label,
      probability: asNumber(probabilities[key]),
      selected:
        selectedText !== '' &&
        (selectedText === key || selectedText === label),
    }
  })
}

export function jevScoreLevels(
  block: JevQuestionBlock | undefined,
): Array<{ key: string; label: string; probability: number | null; selected: boolean }> {
  const legend = block?.legend || {}
  const probabilities = block?.probabilities || {}
  const keys = Object.keys(legend).length > 0 ? Object.keys(legend) : Object.keys(probabilities)
  const selected = block?.value
  return keys.map((key) => {
    const label = legend[key] != null ? String(legend[key]) : key
    return {
      key,
      label,
      probability: asNumber(probabilities[key]),
      selected: selected != null && (String(selected) === label || String(selected) === key),
    }
  })
}

export function jevQuestionTypes(score: JevScore): Array<'noul' | 'choice' | 'score'> {
  const questions = score.questions || {}
  const types: Array<'noul' | 'choice' | 'score'> = []
  for (const key of ['noul', 'choice', 'score'] as const) {
    if (questions[key]) types.push(key)
  }
  if (types.length > 0) return types
  if (score.jev_type === 'noul' || score.jev_type === 'choice' || score.jev_type === 'score') {
    return [score.jev_type]
  }
  return []
}
