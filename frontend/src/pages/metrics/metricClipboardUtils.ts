export type MetricClipboardScope = 'workspace' | 'organization'

export interface MetricClipboardChild {
  name: string
  description: string
  example: string
  enabled: boolean
}

export interface MetricClipboardPayloadBase {
  __efficientai_metric_clipboard__: true
  schema_version: 1
  name: string
  description: string
  supported_surfaces: string[]
  enabled_surfaces: string[]
  tags: string[] | null
  source_scope: MetricClipboardScope
}

export interface MetricClipboardSinglePayload extends MetricClipboardPayloadBase {
  kind: 'single'
  example?: string | null
  metric_type: 'number' | 'boolean' | 'rating' | 'text'
  metric_origin: 'default' | 'custom'
  trigger: 'always'
  capture_rationale: boolean
  compare_transcripts: boolean
  allow_discovery: boolean
  custom_data_type?: 'boolean' | 'enum' | 'number_range' | null
  custom_config?: Record<string, unknown> | null
}

export interface MetricClipboardCategoryPayload extends MetricClipboardPayloadBase {
  kind: 'category'
  selection_mode: 'single_choice' | 'multi_label'
  allow_discovery: boolean
  capture_rationale: boolean
  children: MetricClipboardChild[]
}

export type MetricClipboardPayload =
  | MetricClipboardSinglePayload
  | MetricClipboardCategoryPayload

type MetricLike = {
  name: string
  description?: string
  example?: string | null
  metric_type: 'number' | 'boolean' | 'rating' | 'text'
  metric_origin: 'default' | 'custom'
  supported_surfaces: string[]
  enabled_surfaces: string[]
  custom_data_type?: 'boolean' | 'enum' | 'number_range' | null
  custom_config?: Record<string, unknown> | null
  tags?: string[] | null
  capture_rationale?: boolean
  trigger: 'always'
  allow_discovery?: boolean
  compare_transcripts?: boolean
  parent_metric_id?: string | null
  selection_mode?: 'single_choice' | 'multi_label' | null
  scope?: MetricClipboardScope
  workspace_id?: string | null
  children?: Array<{
    name: string
    description?: string
    example?: string | null
    enabled: boolean
  }>
}

let nextChildLocalId = 0

function newChildLocalId(): string {
  nextChildLocalId += 1
  return `paste-c${nextChildLocalId}`
}

function resolveScope(metric: MetricLike): MetricClipboardScope {
  if (metric.scope) return metric.scope
  return metric.workspace_id == null ? 'organization' : 'workspace'
}

export function serializeMetricToClipboard(metric: MetricLike): MetricClipboardPayload {
  const sourceScope = resolveScope(metric)
  const isParent =
    !!metric.selection_mode && !metric.parent_metric_id

  if (isParent) {
    return {
      __efficientai_metric_clipboard__: true,
      schema_version: 1,
      kind: 'category',
      name: metric.name,
      description: (metric.description || '').trim(),
      selection_mode: metric.selection_mode || 'single_choice',
      allow_discovery: !!metric.allow_discovery,
      capture_rationale: !!metric.capture_rationale,
      supported_surfaces: [...(metric.supported_surfaces || ['agent'])],
      enabled_surfaces: [...(metric.enabled_surfaces || ['agent'])],
      tags: metric.tags ? [...metric.tags] : null,
      source_scope: sourceScope,
      children: (metric.children || [])
        .filter((child) => child.enabled !== false)
        .map((child) => ({
          name: child.name,
          description: (child.description || '').trim(),
          example: (child.example || '').trim(),
          enabled: child.enabled !== false,
        })),
    }
  }

  return {
    __efficientai_metric_clipboard__: true,
    schema_version: 1,
    kind: 'single',
    name: metric.name,
    description: (metric.description || '').trim(),
    example: metric.example ?? null,
    metric_type: metric.metric_type,
    metric_origin: metric.metric_origin || 'custom',
    trigger: metric.trigger || 'always',
    capture_rationale: !!metric.capture_rationale,
    compare_transcripts: !!metric.compare_transcripts,
    allow_discovery: !!metric.allow_discovery,
    custom_data_type: metric.custom_data_type ?? null,
    custom_config: metric.custom_config ?? null,
    supported_surfaces: [...(metric.supported_surfaces || ['agent'])],
    enabled_surfaces: [...(metric.enabled_surfaces || ['agent'])],
    tags: metric.tags ? [...metric.tags] : null,
    source_scope: sourceScope,
  }
}

export function parseMetricClipboardPayload(text: string): MetricClipboardPayload {
  const trimmed = (text || '').trim()
  if (!trimmed) {
    throw new Error('Clipboard is empty.')
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error('Clipboard does not contain valid metric JSON.')
  }

  if (
    !parsed ||
    typeof parsed !== 'object' ||
    (parsed as MetricClipboardPayload).__efficientai_metric_clipboard__ !== true ||
    (parsed as MetricClipboardPayload).schema_version !== 1
  ) {
    throw new Error('Clipboard does not contain a copied EfficientAI metric.')
  }

  const payload = parsed as MetricClipboardPayload
  if (payload.kind !== 'single' && payload.kind !== 'category') {
    throw new Error('Unsupported metric clipboard kind.')
  }
  if (!payload.name?.trim()) {
    throw new Error('Copied metric is missing a name.')
  }

  return payload
}

export function pastedMetricName(originalName: string): string {
  const trimmed = (originalName || '').trim()
  if (!trimmed) return 'Copied metric'
  return trimmed.toLowerCase().startsWith('copy of ')
    ? trimmed
    : `Copy of ${trimmed}`
}

export function singleFormFromMetricClipboard(
  payload: MetricClipboardSinglePayload,
  targetScope: MetricClipboardScope,
) {
  const customDataType =
    payload.custom_data_type ||
    (payload.metric_type === 'rating'
      ? 'enum'
      : payload.metric_type === 'number'
        ? 'number_range'
        : 'boolean')

  return {
    name: pastedMetricName(payload.name),
    description: payload.description || '',
    metric_type: payload.metric_type,
    metric_origin: payload.metric_origin || 'custom',
    supported_surfaces: [...payload.supported_surfaces] as Array<
      'agent' | 'voice_playground' | 'blind_test'
    >,
    enabled_surfaces: [...payload.enabled_surfaces] as Array<
      'agent' | 'voice_playground' | 'blind_test'
    >,
    custom_data_type: customDataType as 'boolean' | 'enum' | 'number_range',
    enum_options_csv: Array.isArray(payload.custom_config?.options)
      ? (payload.custom_config.options as string[]).join(', ')
      : '',
    number_min: Number(payload.custom_config?.min ?? 0),
    number_max: Number(payload.custom_config?.max ?? 10),
    number_step: Number(payload.custom_config?.step ?? 1),
    tags_csv: payload.tags?.join(', ') || '',
    trigger: 'always' as const,
    enabled: true,
    capture_rationale: !!payload.capture_rationale,
    allow_discovery: !!payload.allow_discovery,
    compare_transcripts: !!payload.compare_transcripts,
    scope: targetScope,
  }
}

export function categoryFormFromMetricClipboard(
  payload: MetricClipboardCategoryPayload,
  targetScope: MetricClipboardScope,
) {
  const children = (payload.children || []).filter((child) => child.name.trim())
  return {
    name: pastedMetricName(payload.name),
    description: payload.description || '',
    surfaces: [...payload.supported_surfaces] as Array<
      'agent' | 'voice_playground' | 'blind_test'
    >,
    capture_rationale: !!payload.capture_rationale,
    selection_mode: payload.selection_mode,
    scope: targetScope,
    children:
      children.length > 0
        ? children.map((child) => ({
            local_id: newChildLocalId(),
            name: child.name.trim(),
            description: (child.description || '').trim(),
            example: (child.example || '').trim(),
          }))
        : [{ local_id: newChildLocalId(), name: '', description: '', example: '' }],
  }
}
