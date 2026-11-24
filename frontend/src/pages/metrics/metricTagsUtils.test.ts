import { describe, expect, it } from 'vitest'
import {
  parseTagsCsv,
  tagsForMetricCreate,
  tagsForMetricUpdate,
  tagsCsvFromList,
} from './metricTagsUtils'
import {
  buildClassificationPayload,
  classificationFormFromMetric,
  defaultClassificationForm,
} from './classificationMetricUtils'
import { categoryFormFromMetricClipboard } from './metricClipboardUtils'
import type { MetricClipboardCategoryPayload } from './metricClipboardUtils'

describe('parseTagsCsv', () => {
  it('returns empty for blank input', () => {
    expect(parseTagsCsv('')).toEqual([])
    expect(parseTagsCsv('   ')).toEqual([])
  })

  it('trims and drops empty segments', () => {
    expect(parseTagsCsv(' quality , , compliance ,friendliness ')).toEqual([
      'quality',
      'compliance',
      'friendliness',
    ])
  })

  it('preserves order', () => {
    expect(parseTagsCsv('a, b, c')).toEqual(['a', 'b', 'c'])
  })
})

describe('tagsForMetricCreate / tagsForMetricUpdate', () => {
  it('create omits when empty', () => {
    expect(tagsForMetricCreate('')).toBeUndefined()
    expect(tagsForMetricCreate('qa, compliance')).toEqual(['qa', 'compliance'])
  })

  it('update always returns array', () => {
    expect(tagsForMetricUpdate('')).toEqual([])
    expect(tagsForMetricUpdate('one')).toEqual(['one'])
  })
})

describe('tagsCsvFromList', () => {
  it('joins tags for form display', () => {
    expect(tagsCsvFromList(['a', 'b'])).toBe('a, b')
    expect(tagsCsvFromList(null)).toBe('')
  })
})

describe('classification metric tags', () => {
  const baseForm = () => ({
    ...defaultClassificationForm(),
    name: 'Outcome',
    noul: {
      ...defaultClassificationForm().noul,
      enabled: true,
      instructions: 'Was it resolved?',
      trueCriteria: 'yes',
      falseCriteria: 'no',
    },
    tags_csv: 'routing, qa',
  })

  it('buildClassificationPayload includes tags on create', () => {
    const payload = buildClassificationPayload(baseForm(), false)
    expect(payload.tags).toEqual(['routing', 'qa'])
  })

  it('buildClassificationPayload omits tags when empty on create', () => {
    const form = { ...baseForm(), tags_csv: '' }
    const payload = buildClassificationPayload(form, false)
    expect(payload.tags).toBeUndefined()
  })

  it('buildClassificationPayload sends empty tags on update when cleared', () => {
    const form = { ...baseForm(), tags_csv: '' }
    const payload = buildClassificationPayload(form, true)
    expect(payload.tags).toEqual([])
  })

  it('classificationFormFromMetric restores tags_csv', () => {
    const form = classificationFormFromMetric({
      name: 'X',
      tags: ['tone', 'latency'],
      custom_config: {
        noul: { enabled: true, instructions: 'i', criteria: { true: 't', false: 'f' } },
      },
    })
    expect(form.tags_csv).toBe('tone, latency')
  })
})

describe('categoryFormFromMetricClipboard tags', () => {
  it('restores tags_csv from payload', () => {
    const payload: MetricClipboardCategoryPayload = {
      __efficientai_metric_clipboard__: true,
      schema_version: 1,
      kind: 'category',
      name: 'Outcomes',
      description: 'prompt',
      selection_mode: 'single_choice',
      allow_discovery: false,
      capture_rationale: false,
      supported_surfaces: ['agent'],
      enabled_surfaces: ['agent'],
      tags: ['billing', 'quality'],
      source_scope: 'workspace',
      children: [{ name: 'Resolved', description: 'd', example: '', enabled: true }],
    }
    const form = categoryFormFromMetricClipboard(payload, 'workspace')
    expect(form.tags_csv).toBe('billing, quality')
  })
})
