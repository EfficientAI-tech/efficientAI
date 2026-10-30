import { describe, expect, it } from 'vitest'
import { formatJevCell, jevNeedsReview, jevResponseJson } from './jevScoreDisplay'

describe('formatJevCell', () => {
  it('renders noul as Yes/No with probability', () => {
    expect(
      formatJevCell({
        type: 'jev',
        jev_type: 'noul',
        questions: { noul: { noul: 0.95, value: true } },
      }),
    ).toBe('Yes (0.95)')
    expect(
      formatJevCell({
        type: 'jev',
        jev_type: 'noul',
        questions: { noul: { noul: 0.4, value: false } },
      }),
    ).toBe('No (0.40)')
  })

  it('joins bundle values', () => {
    expect(
      formatJevCell({
        type: 'jev',
        jev_type: 'bundle',
        questions: {
          noul: { noul: 0.95, value: true },
          score: { value: 'Frustrated' },
        },
      }),
    ).toBe('Yes (0.95) · Frustrated')
  })
})

describe('jevNeedsReview', () => {
  it('is false after resolve', () => {
    expect(
      jevNeedsReview({
        type: 'jev',
        needs_review: true,
        review: { resolved: true, resolved_value: 'refund' },
      }),
    ).toBe(false)
  })
})

describe('jevResponseJson', () => {
  it('includes every choice probability', () => {
    expect(
      jevResponseJson(
        {
          type: 'jev',
          questions: {
            choice: {
              choice: 'Complaint',
              value: 'Complaint',
              confidence: 0.8,
              probabilities: { Complaint: 0.8, other: 0.2 },
            },
          },
        },
        'choice',
      ),
    ).toEqual({
      type: 'choice',
      choice: 'Complaint',
      value: 'Complaint',
      probabilities: { Complaint: 0.8, other: 0.2 },
      confidence: 0.8,
    })
  })

  it('omits null confidence', () => {
    expect(
      jevResponseJson(
        {
          type: 'jev',
          questions: {
            choice: { choice: 'other', value: 'other' },
          },
        },
        'choice',
      ),
    ).toEqual({
      type: 'choice',
      choice: 'other',
      value: 'other',
    })
  })

  it('lists every choice option even when probabilities are missing', () => {
    expect(
      jevResponseJson(
        {
          type: 'jev',
          questions: {
            choice: {
              choice: 'Issue in the product',
              value: 'Issue in the product',
              options: {
                'Issue in the product': 'product defect',
                other: 'none',
              },
            },
          },
        },
        'choice',
      ),
    ).toEqual({
      type: 'choice',
      choice: 'Issue in the product',
      value: 'Issue in the product',
      probabilities: {
        'Issue in the product': null,
        other: null,
      },
    })
  })
})
