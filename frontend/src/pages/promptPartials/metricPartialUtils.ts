export interface MetricPartialChild {
  name: string
  description: string
  example: string
}

export interface MetricPartialContent {
  schema_version: 1
  metric_kind: 'single' | 'category'
  description: string
  children?: MetricPartialChild[]
}

export interface ParsedMetricPartial {
  content: MetricPartialContent
  isLegacyPlainText: boolean
}

let nextLocalId = 0

export function newMetricPartialLocalId(prefix = 'mp'): string {
  nextLocalId += 1
  return `${prefix}${nextLocalId}`
}

export function emptyMetricPartialContent(
  metricKind: 'single' | 'category',
): MetricPartialContent {
  return {
    schema_version: 1,
    metric_kind: metricKind,
    description: '',
    ...(metricKind === 'category'
      ? {
          children: [
            { name: '', description: '', example: '' },
          ],
        }
      : {}),
  }
}

export function parseMetricPartialContent(content: string): ParsedMetricPartial {
  const trimmed = (content || '').trim()
  if (!trimmed) {
    return {
      content: {
        schema_version: 1,
        metric_kind: 'single',
        description: '',
      },
      isLegacyPlainText: false,
    }
  }

  try {
    const parsed = JSON.parse(trimmed) as Partial<MetricPartialContent>
    if (
      parsed &&
      typeof parsed === 'object' &&
      (parsed.metric_kind === 'single' || parsed.metric_kind === 'category') &&
      typeof parsed.description === 'string'
    ) {
      const children =
        parsed.metric_kind === 'category'
          ? (parsed.children || []).map((child) => ({
              name: (child?.name || '').trim(),
              description: (child?.description || '').trim(),
              example: (child?.example || '').trim(),
            }))
          : undefined
      return {
        content: {
          schema_version: 1,
          metric_kind: parsed.metric_kind,
          description: (parsed.description || '').trim(),
          ...(parsed.metric_kind === 'category' ? { children } : {}),
        },
        isLegacyPlainText: false,
      }
    }
  } catch {
    // fall through to legacy plain-text handling
  }

  return {
    content: {
      schema_version: 1,
      metric_kind: 'single',
      description: trimmed,
    },
    isLegacyPlainText: true,
  }
}

export function serializeMetricPartialContent(
  content: MetricPartialContent,
): string {
  const payload: MetricPartialContent = {
    schema_version: 1,
    metric_kind: content.metric_kind,
    description: (content.description || '').trim(),
  }

  if (content.metric_kind === 'category') {
    payload.children = (content.children || [])
      .map((child) => ({
        name: (child.name || '').trim(),
        description: (child.description || '').trim(),
        example: (child.example || '').trim(),
      }))
      .filter((child) => child.name)
    if (payload.children.length === 0) {
      delete payload.children
    }
  }

  return JSON.stringify(payload)
}

export function metricPartialHasSaveableContent(
  content: MetricPartialContent,
): boolean {
  if (content.metric_kind === 'single') {
    return !!content.description.trim()
  }
  const namedChildren = (content.children || []).filter((child) => child.name.trim())
  return !!content.description.trim() || namedChildren.length > 0
}

export function formatMetricPartialPreview(content: MetricPartialContent): string {
  if (content.metric_kind === 'single') {
    return content.description || '(empty description)'
  }
  const lines = [
    content.description ? `Context: ${content.description}` : '(no context)',
    '',
    'Labels:',
  ]
  for (const child of content.children || []) {
    lines.push(`- ${child.name || '(unnamed)'}`)
    if (child.description) lines.push(`  Definition: ${child.description}`)
    if (child.example) lines.push(`  Example: ${child.example}`)
  }
  return lines.join('\n')
}

export function categoryChildrenFromPartial(
  children: MetricPartialChild[] | undefined,
  mode: 'create' | 'edit',
): Array<{
  local_id: string
  server_id: string | null
  name: string
  description: string
  example: string
  enabled: boolean
}> {
  const rows = (children || []).filter((child) => child.name.trim())
  if (rows.length === 0) {
    return [
      {
        local_id: newMetricPartialLocalId('c'),
        server_id: null,
        name: '',
        description: '',
        example: '',
        enabled: true,
      },
    ]
  }
  return rows.map((child) => ({
    local_id: newMetricPartialLocalId('c'),
    server_id: mode === 'edit' ? null : null,
    name: child.name.trim(),
    description: child.description.trim(),
    example: child.example.trim(),
    enabled: true,
  }))
}

export function createCategoryChildrenFromPartial(
  children: MetricPartialChild[] | undefined,
): Array<{
  local_id: string
  name: string
  description: string
  example: string
}> {
  const rows = (children || []).filter((child) => child.name.trim())
  if (rows.length === 0) {
    return [
      {
        local_id: newMetricPartialLocalId('c'),
        name: '',
        description: '',
        example: '',
      },
    ]
  }
  return rows.map((child) => ({
    local_id: newMetricPartialLocalId('c'),
    name: child.name.trim(),
    description: child.description.trim(),
    example: child.example.trim(),
  }))
}
