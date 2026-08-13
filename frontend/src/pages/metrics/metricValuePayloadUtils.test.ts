import { describe, expect, it } from 'vitest'
import {
  buildSingleMetricValuePayload,
  formatMetricValuePayloadJson,
  type SingleMetricFormSnapshot,
} from './metricValuePayloadUtils'

const baseForm: SingleMetricFormSnapshot = {
  name: 'Booking Confirmation',
  description: 'True when the agent confirms the booking date and time.',
  metric_type: 'boolean',
  custom_data_type: 'boolean',
  enum_options_csv: '',
  number_min: 0,
  number_max: 10,
  capture_rationale: false,
}

describe('buildSingleMetricValuePayload', () => {
  it('builds boolean payload without rationale', () => {
    const payload = buildSingleMetricValuePayload(baseForm)
    expect(payload).toEqual({
      value: true,
      type: 'boolean',
      metric_name: 'Booking Confirmation',
      description: 'True when the agent confirms the booking date and time.',
    })
  })

  it('includes rationale when capture_rationale is enabled', () => {
    const payload = buildSingleMetricValuePayload({
      ...baseForm,
      capture_rationale: true,
    })
    expect(payload.rationale).toBeTruthy()
    expect(payload.type).toBe('boolean')
  })

  it('builds enum payload with options and first option as value', () => {
    const payload = buildSingleMetricValuePayload({
      ...baseForm,
      metric_type: 'rating',
      custom_data_type: 'enum',
      enum_options_csv: 'Excellent, Good, Poor',
    })
    expect(payload).toMatchObject({
      value: 'Excellent',
      type: 'enum',
      metric_name: 'Booking Confirmation',
      description: 'True when the agent confirms the booking date and time.',
      options: ['Excellent', 'Good', 'Poor'],
    })
  })

  it('builds number payload using midpoint of min and max', () => {
    const payload = buildSingleMetricValuePayload({
      ...baseForm,
      metric_type: 'number',
      custom_data_type: 'number_range',
      number_min: 0,
      number_max: 10,
    })
    expect(payload).toEqual({
      value: 5,
      type: 'number',
      metric_name: 'Booking Confirmation',
      description: 'True when the agent confirms the booking date and time.',
    })
  })

  it('builds text payload without rationale even when capture_rationale is on', () => {
    const payload = buildSingleMetricValuePayload({
      ...baseForm,
      metric_type: 'text',
      custom_data_type: 'boolean',
      capture_rationale: true,
    })
    expect(payload.type).toBe('text')
    expect(typeof payload.value).toBe('string')
    expect(payload.rationale).toBeUndefined()
  })

  it('uses empty description when description is blank', () => {
    const payload = buildSingleMetricValuePayload({
      ...baseForm,
      description: '   ',
    })
    expect(payload.description).toBe('')
  })

  it('uses placeholder name when metric name is empty', () => {
    const payload = buildSingleMetricValuePayload({
      ...baseForm,
      name: '   ',
    })
    expect(payload.metric_name).toBe('(unnamed metric)')
  })
})

describe('formatMetricValuePayloadJson', () => {
  it('returns pretty-printed JSON', () => {
    const json = formatMetricValuePayloadJson(
      buildSingleMetricValuePayload(baseForm),
    )
    expect(json).toContain('"type": "boolean"')
    expect(JSON.parse(json)).toBeTruthy()
  })
})
